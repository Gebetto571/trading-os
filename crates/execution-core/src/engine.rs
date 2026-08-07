//! Pure deterministic reducer and compatibility admission wrapper.

use std::collections::BTreeMap;

use crate::event::{CoreMessage, EngineInput, EventProvenance, ExternalEvent};
use crate::order::{
    validate_intent, Order, OrderCommand, OrderIntent, OrderTransitionError, OrderValidationError,
};
use crate::portfolio::{FundedSpotPortfolio, PaperPortfolioSeed};
use crate::risk::{FundedSpotRiskLimits, RiskRejection};
use crate::types::{
    EngineSeq, FillId, Instrument, InstrumentSpec, IntentId, OrderId, PriceTicks, Side,
    SignedBtcAtoms, SignedUsdtAtoms, StateHash, VirtualClock,
};

/// Version tag written first by [`EngineState::canonical_bytes`].
pub const STATE_ENCODING_V1: u8 = 1;
pub const STATE_ENCODING_V2: u8 = 2;
pub const STATE_ENCODING_V3: u8 = 3;
const FNV1A_64_OFFSET_BASIS: u64 = 0xcbf2_9ce4_8422_2325;
const FNV1A_64_PRIME: u64 = 0x0000_0100_0000_01b3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EngineError {
    UnexpectedSequence {
        expected: EngineSeq,
        received: EngineSeq,
    },
    SequenceExhausted {
        last: EngineSeq,
        received: EngineSeq,
    },
    DuplicateFill {
        fill_id: FillId,
        first_sequence: EngineSeq,
        received_sequence: EngineSeq,
    },
    DuplicateIntentId {
        intent_id: IntentId,
        first_sequence: EngineSeq,
        received_sequence: EngineSeq,
    },
    IntentConflict {
        intent_id: IntentId,
        first_sequence: EngineSeq,
        received_sequence: EngineSeq,
    },
    OrderIdExhausted,
    OrderValidation {
        intent_id: IntentId,
        error: OrderValidationError,
    },
    UnknownOrder {
        order_id: OrderId,
    },
    OrderTransition {
        order_id: OrderId,
        error: OrderTransitionError,
    },
    FillInstrumentMismatch {
        order_id: OrderId,
        expected: Instrument,
        received: Instrument,
    },
    FillSideMismatch {
        order_id: OrderId,
        expected: Side,
        received: Side,
    },
    FillPriceOutsideLimit {
        order_id: OrderId,
        limit: PriceTicks,
        received: PriceTicks,
    },
    PortfolioAmountOutOfRange,
    PortfolioArithmeticOverflow,
    RiskReject(RiskRejection),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FundedSpotConfig {
    pub seed: PaperPortfolioSeed,
    pub limits: FundedSpotRiskLimits,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct StoredOrder {
    order: Order,
}

/// Immutable reducer state. Its fields stay private so every accepted change
/// passes through [`reduce`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineState {
    encoding_version: u8,
    spec: InstrumentSpec,
    last_engine_seq: Option<EngineSeq>,
    last_provenance: Option<EventProvenance>,
    virtual_clock: Option<VirtualClock>,
    seen_fills: BTreeMap<FillId, EngineSeq>,
    orders: BTreeMap<OrderId, StoredOrder>,
    intents: BTreeMap<IntentId, (OrderId, EngineSeq, OrderIntent)>,
    last_market_prices: BTreeMap<Instrument, PriceTicks>,
    next_order_id: Option<u64>,
    positions: BTreeMap<Instrument, SignedBtcAtoms>,
    quote_cash: SignedUsdtAtoms,
    funded_spot: Option<FundedSpotState>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FundedSpotState {
    seed: PaperPortfolioSeed,
    limits: FundedSpotRiskLimits,
    portfolio: FundedSpotPortfolio,
}

impl EngineState {
    pub fn new(spec: InstrumentSpec) -> Self {
        Self::with_encoding(spec, STATE_ENCODING_V2)
    }

    /// Constructs a legacy V1 state for compatibility-vector verification only.
    pub fn new_v1(spec: InstrumentSpec) -> Self {
        Self::with_encoding(spec, STATE_ENCODING_V1)
    }

    /// Starts a deterministic paper-only, funded long-only spot state.
    pub fn new_funded_spot(spec: InstrumentSpec, config: FundedSpotConfig) -> Self {
        let mut state = Self::with_encoding(spec, STATE_ENCODING_V3);
        state.funded_spot = Some(FundedSpotState {
            seed: config.seed,
            limits: config.limits,
            portfolio: FundedSpotPortfolio::from_seed(config.seed),
        });
        state
    }

    fn with_encoding(spec: InstrumentSpec, encoding_version: u8) -> Self {
        Self {
            encoding_version,
            spec,
            last_engine_seq: None,
            last_provenance: None,
            virtual_clock: None,
            seen_fills: BTreeMap::new(),
            orders: BTreeMap::new(),
            intents: BTreeMap::new(),
            last_market_prices: BTreeMap::new(),
            next_order_id: Some(1),
            positions: BTreeMap::new(),
            quote_cash: SignedUsdtAtoms::ZERO,
            funded_spot: None,
        }
    }

    pub const fn spec(&self) -> InstrumentSpec {
        self.spec
    }
    pub const fn encoding_version(&self) -> u8 {
        self.encoding_version
    }
    pub fn net_base_atoms(&self, instrument: Instrument) -> SignedBtcAtoms {
        self.positions
            .get(&instrument)
            .copied()
            .unwrap_or(SignedBtcAtoms::ZERO)
    }
    pub const fn quote_cash_atoms(&self) -> SignedUsdtAtoms {
        self.quote_cash
    }
    pub fn funded_spot_portfolio(&self) -> Option<&FundedSpotPortfolio> {
        self.funded_spot.as_ref().map(|value| &value.portfolio)
    }
    pub const fn last_engine_seq(&self) -> Option<EngineSeq> {
        self.last_engine_seq
    }
    pub const fn last_provenance(&self) -> Option<EventProvenance> {
        self.last_provenance
    }
    pub const fn virtual_clock(&self) -> Option<VirtualClock> {
        self.virtual_clock
    }
    pub fn fill_sequence(&self, fill_id: FillId) -> Option<EngineSeq> {
        self.seen_fills.get(&fill_id).copied()
    }
    pub fn order(&self, order_id: OrderId) -> Option<&Order> {
        self.orders.get(&order_id).map(|entry| &entry.order)
    }
    pub fn order_for_intent(&self, intent_id: IntentId) -> Option<&Order> {
        self.intents
            .get(&intent_id)
            .and_then(|(order_id, _, _)| self.order(*order_id))
    }
    pub fn last_market_price(&self, instrument: Instrument) -> Option<PriceTicks> {
        self.last_market_prices.get(&instrument).copied()
    }

    /// Stable V1 bytes: big-endian integers, tagged options/enums, and BTreeMap
    /// natural order. This intentionally excludes process and runtime state.
    pub fn canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = self.canonical_v1_bytes();
        if self.encoding_version == STATE_ENCODING_V2 || self.encoding_version == STATE_ENCODING_V3
        {
            bytes[0] = STATE_ENCODING_V2;
            encode_len(&mut bytes, self.positions.len());
            for (instrument, base) in &self.positions {
                encode_instrument(&mut bytes, *instrument);
                push_i128(&mut bytes, base.get());
            }
            push_i128(&mut bytes, self.quote_cash.get());
        }
        if self.encoding_version == STATE_ENCODING_V3 {
            bytes[0] = STATE_ENCODING_V3;
            match self.funded_spot {
                Some(value) => {
                    bytes.push(1);
                    encode_funded_spot(&mut bytes, value);
                }
                None => bytes.push(0),
            }
        }
        bytes
    }

    /// Frozen V1 byte contract. V2 state is never hashed through this method.
    pub fn canonical_v1_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.push(STATE_ENCODING_V1);
        encode_spec(&mut bytes, self.spec);
        encode_option_u64(&mut bytes, self.last_engine_seq.map(EngineSeq::get));
        match self.last_provenance {
            Some(value) => {
                bytes.push(1);
                encode_provenance(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        encode_option_i64(
            &mut bytes,
            self.virtual_clock
                .map(|value| value.source_event_time().get()),
        );
        encode_option_u64(&mut bytes, self.next_order_id);
        encode_len(&mut bytes, self.seen_fills.len());
        for (fill_id, sequence) in &self.seen_fills {
            push_u64(&mut bytes, fill_id.get());
            push_u64(&mut bytes, sequence.get());
        }
        encode_len(&mut bytes, self.orders.len());
        for (order_id, stored) in &self.orders {
            push_u64(&mut bytes, order_id.get());
            encode_order(&mut bytes, stored.order);
        }
        encode_len(&mut bytes, self.intents.len());
        for (intent_id, (order_id, sequence, intent)) in &self.intents {
            push_u64(&mut bytes, intent_id.get());
            push_u64(&mut bytes, order_id.get());
            push_u64(&mut bytes, sequence.get());
            encode_intent(&mut bytes, *intent);
        }
        encode_len(&mut bytes, self.last_market_prices.len());
        for (instrument, price) in &self.last_market_prices {
            encode_instrument(&mut bytes, *instrument);
            push_u64(&mut bytes, price.get());
        }
        bytes
    }

    pub fn state_hash(&self) -> StateHash {
        StateHash::new(fnv1a_64(&self.canonical_bytes()))
    }
}

/// An accepted domain change in reducer order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DomainEffect {
    MarketPriceUpdated {
        instrument: Instrument,
        price: PriceTicks,
    },
    OrderAccepted {
        order_id: OrderId,
        intent_id: IntentId,
    },
    OrderCancelled {
        order_id: OrderId,
    },
    FillRecorded {
        fill_id: FillId,
    },
    FillApplied {
        fill_id: FillId,
        order_id: OrderId,
    },
    SpotPortfolioUpdated {
        instrument: Instrument,
        base: SignedBtcAtoms,
        quote_cash: SignedUsdtAtoms,
    },
}

/// The successful, immutable result of a reducer call.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Transition {
    pub state: EngineState,
    pub effects: Vec<DomainEffect>,
    pub provenance: EventProvenance,
    pub state_hash: StateHash,
}

/// Reduces one normalized input without modifying `state`.
pub fn reduce(state: &EngineState, input: &EngineInput) -> Result<Transition, EngineError> {
    validate_sequence(state, input.engine_seq)?;

    let fill_id = match input.message {
        CoreMessage::External(ExternalEvent::Fill(fill)) => Some(fill.fill_id),
        _ => None,
    };
    if let Some(fill_id) = fill_id {
        if let Some(first_sequence) = state.seen_fills.get(&fill_id).copied() {
            return Err(EngineError::DuplicateFill {
                fill_id,
                first_sequence,
                received_sequence: input.engine_seq,
            });
        }
    }

    let mut next = state.clone();
    let effects =
        match input.message {
            CoreMessage::External(ExternalEvent::MarketTrade(trade)) => {
                next.last_market_prices
                    .insert(trade.instrument, trade.price);
                vec![DomainEffect::MarketPriceUpdated {
                    instrument: trade.instrument,
                    price: trade.price,
                }]
            }
            CoreMessage::Command(OrderCommand::Submit(intent)) => {
                if let Some((_, first_sequence, original)) = state.intents.get(&intent.intent_id) {
                    return if original == &intent {
                        Err(EngineError::DuplicateIntentId {
                            intent_id: intent.intent_id,
                            first_sequence: *first_sequence,
                            received_sequence: input.engine_seq,
                        })
                    } else {
                        Err(EngineError::IntentConflict {
                            intent_id: intent.intent_id,
                            first_sequence: *first_sequence,
                            received_sequence: input.engine_seq,
                        })
                    };
                }
                let reference_price = state.last_market_price(intent.instrument);
                validate_intent(&intent, state.spec, reference_price).map_err(|error| {
                    EngineError::OrderValidation {
                        intent_id: intent.intent_id,
                        error,
                    }
                })?;
                reserve_for_submission(&mut next, intent)?;
                let raw_order_id = next.next_order_id.ok_or(EngineError::OrderIdExhausted)?;
                let order_id = OrderId::new(raw_order_id).ok_or(EngineError::OrderIdExhausted)?;
                next.next_order_id = raw_order_id.checked_add(1);
                next.orders.insert(
                    order_id,
                    StoredOrder {
                        order: Order::open(order_id, intent),
                    },
                );
                next.intents
                    .insert(intent.intent_id, (order_id, input.engine_seq, intent));
                vec![DomainEffect::OrderAccepted {
                    order_id,
                    intent_id: intent.intent_id,
                }]
            }
            CoreMessage::Command(OrderCommand::Cancel(cancel)) => {
                let mut staged = state.orders.get(&cancel.order_id).copied().ok_or(
                    EngineError::UnknownOrder {
                        order_id: cancel.order_id,
                    },
                )?;
                staged
                    .order
                    .cancel()
                    .map_err(|error| EngineError::OrderTransition {
                        order_id: cancel.order_id,
                        error,
                    })?;
                release_for_cancel(
                    &mut next,
                    *staged.order.definition(),
                    staged.order.remaining_quantity(),
                )?;
                next.orders.insert(cancel.order_id, staged);
                vec![DomainEffect::OrderCancelled {
                    order_id: cancel.order_id,
                }]
            }
            CoreMessage::External(ExternalEvent::Fill(fill)) => {
                if state.encoding_version != STATE_ENCODING_V2
                    && state.encoding_version != STATE_ENCODING_V3
                {
                    return Err(EngineError::PortfolioArithmeticOverflow);
                }
                let mut staged =
                    state
                        .orders
                        .get(&fill.order_id)
                        .copied()
                        .ok_or(EngineError::UnknownOrder {
                            order_id: fill.order_id,
                        })?;
                let definition = *staged.order.definition();
                if fill.instrument != definition.instrument {
                    return Err(EngineError::FillInstrumentMismatch {
                        order_id: fill.order_id,
                        expected: definition.instrument,
                        received: fill.instrument,
                    });
                }
                if fill.side != definition.side {
                    return Err(EngineError::FillSideMismatch {
                        order_id: fill.order_id,
                        expected: definition.side,
                        received: fill.side,
                    });
                }
                if let crate::order::OrderKind::Limit { price: limit } = definition.kind {
                    let outside = match definition.side {
                        Side::Buy => fill.price.get() > limit.get(),
                        Side::Sell => fill.price.get() < limit.get(),
                    };
                    if outside {
                        return Err(EngineError::FillPriceOutsideLimit {
                            order_id: fill.order_id,
                            limit,
                            received: fill.price,
                        });
                    }
                }
                staged.order.apply_fill(fill.quantity).map_err(|error| {
                    EngineError::OrderTransition {
                        order_id: fill.order_id,
                        error,
                    }
                })?;
                let base_atoms = u128::from(fill.quantity.get())
                    .checked_mul(state.spec.lot_size().get())
                    .ok_or(EngineError::PortfolioArithmeticOverflow)?;
                let base_atoms =
                    SignedBtcAtoms::from_atoms(crate::types::BtcAtoms::new(base_atoms))
                        .ok_or(EngineError::PortfolioAmountOutOfRange)?;
                let quote_atoms = state
                    .spec
                    .notional(fill.price, fill.quantity)
                    .ok_or(EngineError::PortfolioArithmeticOverflow)?;
                let quote_atoms = SignedUsdtAtoms::from_atoms(quote_atoms)
                    .ok_or(EngineError::PortfolioAmountOutOfRange)?;
                let (base_delta, quote_delta) = match fill.side {
                    Side::Buy => (base_atoms.get(), -quote_atoms.get()),
                    Side::Sell => (-base_atoms.get(), quote_atoms.get()),
                };
                let position = state
                    .net_base_atoms(fill.instrument)
                    .checked_add(base_delta)
                    .ok_or(EngineError::PortfolioArithmeticOverflow)?;
                let quote_cash = state
                    .quote_cash
                    .checked_add(quote_delta)
                    .ok_or(EngineError::PortfolioArithmeticOverflow)?;
                apply_funded_fill(&mut next, definition, fill)?;
                next.orders.insert(fill.order_id, staged);
                if position == SignedBtcAtoms::ZERO {
                    next.positions.remove(&fill.instrument);
                } else {
                    next.positions.insert(fill.instrument, position);
                }
                next.quote_cash = quote_cash;
                vec![
                    DomainEffect::FillApplied {
                        fill_id: fill.fill_id,
                        order_id: fill.order_id,
                    },
                    DomainEffect::SpotPortfolioUpdated {
                        instrument: fill.instrument,
                        base: position,
                        quote_cash,
                    },
                    DomainEffect::FillRecorded {
                        fill_id: fill.fill_id,
                    },
                ]
            }
        };

    if let Some(fill_id) = fill_id {
        next.seen_fills.insert(fill_id, input.engine_seq);
    }
    let provenance = input.provenance();
    next.last_engine_seq = Some(input.engine_seq);
    next.last_provenance = Some(provenance);
    next.virtual_clock = Some(VirtualClock::from_source_event_time(
        input.source_event_time,
    ));
    let state_hash = next.state_hash();
    Ok(Transition {
        state: next,
        effects,
        provenance,
        state_hash,
    })
}

/// Mutable compatibility API for existing callers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionCore {
    state: EngineState,
}

impl ExecutionCore {
    pub fn new(spec: InstrumentSpec) -> Self {
        Self {
            state: EngineState::new(spec),
        }
    }
    /// Starts the same compatibility wrapper over a funded, paper-only V3 state.
    pub fn new_funded_spot(spec: InstrumentSpec, config: FundedSpotConfig) -> Self {
        Self {
            state: EngineState::new_funded_spot(spec, config),
        }
    }
    pub const fn state(&self) -> &EngineState {
        &self.state
    }
    pub const fn spec(&self) -> InstrumentSpec {
        self.state.spec()
    }
    pub const fn last_engine_seq(&self) -> Option<EngineSeq> {
        self.state.last_engine_seq()
    }
    pub const fn last_sequence(&self) -> Option<EngineSeq> {
        self.last_engine_seq()
    }
    pub fn fill_sequence(&self, fill_id: FillId) -> Option<EngineSeq> {
        self.state.fill_sequence(fill_id)
    }
    pub fn order(&self, order_id: OrderId) -> Option<&Order> {
        self.state.order(order_id)
    }
    pub fn order_for_intent(&self, intent_id: IntentId) -> Option<&Order> {
        self.state.order_for_intent(intent_id)
    }
    pub fn last_market_price(&self, instrument: Instrument) -> Option<PriceTicks> {
        self.state.last_market_price(instrument)
    }
    pub fn state_hash(&self) -> StateHash {
        self.state.state_hash()
    }
    pub fn accept(&mut self, input: &EngineInput) -> Result<(), EngineError> {
        let transition = reduce(&self.state, input)?;
        self.state = transition.state;
        Ok(())
    }
}

fn validate_sequence(state: &EngineState, received: EngineSeq) -> Result<(), EngineError> {
    if let Some(last) = state.last_engine_seq {
        let expected = last
            .checked_next()
            .ok_or(EngineError::SequenceExhausted { last, received })?;
        if received != expected {
            return Err(EngineError::UnexpectedSequence { expected, received });
        }
    }
    Ok(())
}

fn base_atoms(
    spec: InstrumentSpec,
    quantity: crate::types::QuantityLots,
) -> Result<crate::types::BtcAtoms, EngineError> {
    let amount = u128::from(quantity.get())
        .checked_mul(spec.lot_size().get())
        .ok_or(EngineError::PortfolioArithmeticOverflow)?;
    Ok(crate::types::BtcAtoms::new(amount))
}

fn reserve_for_submission(next: &mut EngineState, intent: OrderIntent) -> Result<(), EngineError> {
    // This is deliberately derived from open buy orders, not from the seed or
    // the portfolio inventory. `max_open_base` limits requested buy exposure;
    // a funded account with BTC inventory must not consume that limit merely
    // because it already owns BTC.
    let open_buy_base = open_buy_base_atoms(next)?;
    let Some(funded) = next.funded_spot.as_mut() else {
        return Ok(());
    };
    let limits = funded.limits;
    if let Some(maximum) = limits
        .max_single_order
        .filter(|maximum| intent.quantity.get() > maximum.get())
    {
        return Err(EngineError::RiskReject(
            RiskRejection::SingleOrderQuantityExceeded {
                maximum,
                received: intent.quantity,
            },
        ));
    }
    let base = base_atoms(next.spec, intent.quantity)?;
    match (intent.side, intent.kind) {
        (Side::Buy, crate::order::OrderKind::Market) => Err(EngineError::RiskReject(
            RiskRejection::MarketOrderRequiresBoundedPrice,
        )),
        (Side::Buy, crate::order::OrderKind::Limit { price }) => {
            let requested_open =
                open_buy_base
                    .get()
                    .checked_add(base.get())
                    .ok_or(EngineError::RiskReject(
                        RiskRejection::ReservationArithmeticOverflow,
                    ))?;
            if let Some(maximum) = limits
                .max_open_base
                .filter(|maximum| requested_open > maximum.get())
            {
                return Err(EngineError::RiskReject(
                    RiskRejection::OpenBaseLimitExceeded {
                        maximum,
                        requested: crate::types::BtcAtoms::new(requested_open),
                    },
                ));
            }
            let quote =
                next.spec
                    .notional(price, intent.quantity)
                    .ok_or(EngineError::RiskReject(
                        RiskRejection::ReservationArithmeticOverflow,
                    ))?;
            let requested_reserved = funded
                .portfolio
                .reserved_usdt()
                .get()
                .checked_add(quote.get())
                .ok_or(EngineError::RiskReject(
                    RiskRejection::ReservationArithmeticOverflow,
                ))?;
            if let Some(maximum) = limits
                .max_reserved_usdt
                .filter(|maximum| requested_reserved > maximum.get())
            {
                return Err(EngineError::RiskReject(
                    RiskRejection::ReservedUsdtLimitExceeded {
                        maximum,
                        requested: crate::types::UsdtAtoms::new(requested_reserved),
                    },
                ));
            }
            if funded.portfolio.available_usdt().get() < quote.get() {
                return Err(EngineError::RiskReject(
                    RiskRejection::InsufficientAvailableUsdt {
                        required: quote,
                        available: funded.portfolio.available_usdt(),
                    },
                ));
            }
            funded
                .portfolio
                .reserve_usdt(quote)
                .ok_or(EngineError::RiskReject(
                    RiskRejection::ReservationArithmeticOverflow,
                ))
        }
        (Side::Sell, _) => {
            if funded.portfolio.available_btc().get() < base.get() {
                return Err(EngineError::RiskReject(
                    RiskRejection::InsufficientAvailableBtc {
                        required: base,
                        available: funded.portfolio.available_btc(),
                    },
                ));
            }
            funded
                .portfolio
                .reserve_btc(base)
                .ok_or(EngineError::RiskReject(
                    RiskRejection::ReservationArithmeticOverflow,
                ))
        }
    }
}

fn open_buy_base_atoms(state: &EngineState) -> Result<crate::types::BtcAtoms, EngineError> {
    state
        .orders
        .values()
        .try_fold(crate::types::BtcAtoms::ZERO, |total, stored| {
            let order = stored.order;
            if order.is_terminal() || order.definition().side != Side::Buy {
                return Ok(total);
            }
            let remaining = crate::types::QuantityLots::new(order.remaining_quantity().get())
                .ok_or(EngineError::PortfolioArithmeticOverflow)?;
            let amount = base_atoms(state.spec, remaining)?;
            total
                .get()
                .checked_add(amount.get())
                .map(crate::types::BtcAtoms::new)
                .ok_or(EngineError::PortfolioArithmeticOverflow)
        })
}

fn release_for_cancel(
    next: &mut EngineState,
    definition: OrderIntent,
    remaining: crate::order::LotCount,
) -> Result<(), EngineError> {
    let Some(funded) = next.funded_spot.as_mut() else {
        return Ok(());
    };
    let quantity = crate::types::QuantityLots::new(remaining.get())
        .ok_or(EngineError::PortfolioArithmeticOverflow)?;
    match (definition.side, definition.kind) {
        (Side::Buy, crate::order::OrderKind::Limit { price }) => {
            let quote = next
                .spec
                .notional(price, quantity)
                .ok_or(EngineError::PortfolioArithmeticOverflow)?;
            funded
                .portfolio
                .release_usdt(quote)
                .ok_or(EngineError::PortfolioArithmeticOverflow)
        }
        (Side::Sell, _) => funded
            .portfolio
            .release_btc(base_atoms(next.spec, quantity)?)
            .ok_or(EngineError::PortfolioArithmeticOverflow),
        (Side::Buy, crate::order::OrderKind::Market) => Err(EngineError::RiskReject(
            RiskRejection::MarketOrderRequiresBoundedPrice,
        )),
    }
}

fn apply_funded_fill(
    next: &mut EngineState,
    definition: OrderIntent,
    fill: crate::event::ExternalFill,
) -> Result<(), EngineError> {
    let Some(funded) = next.funded_spot.as_mut() else {
        return Ok(());
    };
    let base = base_atoms(next.spec, fill.quantity)?;
    let quote = next
        .spec
        .notional(fill.price, fill.quantity)
        .ok_or(EngineError::PortfolioArithmeticOverflow)?;
    match (definition.side, definition.kind) {
        (Side::Buy, crate::order::OrderKind::Limit { price }) => {
            let reserved = next
                .spec
                .notional(price, fill.quantity)
                .ok_or(EngineError::PortfolioArithmeticOverflow)?;
            let released = crate::types::UsdtAtoms::new(
                reserved
                    .get()
                    .checked_sub(quote.get())
                    .ok_or(EngineError::PortfolioArithmeticOverflow)?,
            );
            funded
                .portfolio
                .apply_buy(base, quote, released)
                .ok_or(EngineError::PortfolioArithmeticOverflow)
        }
        (Side::Sell, _) => funded
            .portfolio
            .apply_sell(base, quote)
            .ok_or(EngineError::PortfolioArithmeticOverflow),
        (Side::Buy, crate::order::OrderKind::Market) => Err(EngineError::RiskReject(
            RiskRejection::MarketOrderRequiresBoundedPrice,
        )),
    }
}

fn fnv1a_64(bytes: &[u8]) -> u64 {
    bytes.iter().fold(FNV1A_64_OFFSET_BASIS, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV1A_64_PRIME)
    })
}
fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn push_u128(bytes: &mut Vec<u8>, value: u128) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn push_i128(bytes: &mut Vec<u8>, value: i128) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn encode_len(bytes: &mut Vec<u8>, value: usize) {
    push_u128(bytes, value as u128);
}
fn encode_option_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u64(bytes, value);
        }
        None => bytes.push(0),
    }
}
fn encode_option_i64(bytes: &mut Vec<u8>, value: Option<i64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_i64(bytes, value);
        }
        None => bytes.push(0),
    }
}
fn encode_option_u128(bytes: &mut Vec<u8>, value: Option<u128>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u128(bytes, value);
        }
        None => bytes.push(0),
    }
}
fn encode_instrument(bytes: &mut Vec<u8>, value: Instrument) {
    bytes.push(match value {
        Instrument::BtcUsdt => 1,
    });
}
fn encode_side(bytes: &mut Vec<u8>, value: crate::types::Side) {
    bytes.push(match value {
        crate::types::Side::Buy => 1,
        crate::types::Side::Sell => 2,
    });
}
fn encode_spec(bytes: &mut Vec<u8>, value: InstrumentSpec) {
    encode_instrument(bytes, value.instrument());
    push_u128(bytes, value.tick_size().get());
    push_u128(bytes, value.lot_size().get());
    push_u64(bytes, value.min_quantity().get());
    push_u128(bytes, value.min_notional().get());
}
fn encode_provenance(bytes: &mut Vec<u8>, value: EventProvenance) {
    push_u64(bytes, value.engine_seq.get());
    push_u64(bytes, value.source_id.get());
    encode_option_u64(bytes, value.source_seq.map(crate::types::SourceSeq::get));
    push_i64(bytes, value.source_event_time.get());
}
fn encode_intent(bytes: &mut Vec<u8>, value: OrderIntent) {
    push_u64(bytes, value.intent_id.get());
    encode_instrument(bytes, value.instrument);
    encode_side(bytes, value.side);
    match value.kind {
        crate::order::OrderKind::Market => bytes.push(1),
        crate::order::OrderKind::Limit { price } => {
            bytes.push(2);
            push_u64(bytes, price.get());
        }
    }
    push_u64(bytes, value.quantity.get());
}
fn encode_order(bytes: &mut Vec<u8>, value: Order) {
    push_u64(bytes, value.id().get());
    encode_intent(bytes, *value.definition());
    push_u64(bytes, value.filled_quantity().get());
    bytes.push(match value.status() {
        crate::order::OrderStatus::Open => 1,
        crate::order::OrderStatus::PartiallyFilled => 2,
        crate::order::OrderStatus::Filled => 3,
        crate::order::OrderStatus::Cancelled => 4,
    });
}
fn encode_funded_spot(bytes: &mut Vec<u8>, value: FundedSpotState) {
    push_u128(bytes, value.seed.btc.get());
    push_u128(bytes, value.seed.usdt.get());
    encode_option_u64(
        bytes,
        value
            .limits
            .max_single_order
            .map(crate::types::OrderQuantityLimit::get),
    );
    encode_option_u128(
        bytes,
        value.limits.max_open_base.map(crate::types::BtcAtoms::get),
    );
    encode_option_u128(
        bytes,
        value
            .limits
            .max_reserved_usdt
            .map(crate::types::UsdtAtoms::get),
    );
    push_u128(bytes, value.portfolio.available_btc().get());
    push_u128(bytes, value.portfolio.reserved_btc().get());
    push_u128(bytes, value.portfolio.available_usdt().get());
    push_u128(bytes, value.portfolio.reserved_usdt().get());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::{ExternalFill, MarketTrade};
    use crate::order::{CancelOrder, NewOrder, OrderKind, OrderStatus};
    use crate::types::{
        BtcAtoms, QuantityLots, Side, SourceId, SourceSeq, TimestampMicros, UsdtAtoms,
    };

    fn spec() -> InstrumentSpec {
        InstrumentSpec::new(
            Instrument::BtcUsdt,
            UsdtAtoms::new(1),
            BtcAtoms::new(1),
            QuantityLots::new(1).unwrap(),
            UsdtAtoms::new(100),
        )
        .unwrap()
    }
    fn input(sequence: u64, time: i64, message: CoreMessage) -> EngineInput {
        EngineInput {
            engine_seq: EngineSeq::new(sequence),
            source_id: SourceId::new(1).unwrap(),
            source_seq: None,
            source_event_time: TimestampMicros::new(time),
            message,
        }
    }
    fn market_input(sequence: u64, time: i64, price: u64) -> EngineInput {
        input(
            sequence,
            time,
            CoreMessage::External(ExternalEvent::MarketTrade(MarketTrade {
                instrument: Instrument::BtcUsdt,
                price: PriceTicks::new(price).unwrap(),
                quantity: QuantityLots::new(1).unwrap(),
            })),
        )
    }
    fn limit_order(
        sequence: u64,
        time: i64,
        intent_id: u64,
        price: u64,
        quantity: u64,
    ) -> EngineInput {
        input(
            sequence,
            time,
            CoreMessage::Command(OrderCommand::Submit(NewOrder {
                intent_id: IntentId::new(intent_id).unwrap(),
                instrument: Instrument::BtcUsdt,
                side: Side::Buy,
                kind: OrderKind::Limit {
                    price: PriceTicks::new(price).unwrap(),
                },
                quantity: QuantityLots::new(quantity).unwrap(),
            })),
        )
    }
    fn market_order(sequence: u64, time: i64, intent_id: u64, quantity: u64) -> EngineInput {
        input(
            sequence,
            time,
            CoreMessage::Command(OrderCommand::Submit(NewOrder {
                intent_id: IntentId::new(intent_id).unwrap(),
                instrument: Instrument::BtcUsdt,
                side: Side::Buy,
                kind: OrderKind::Market,
                quantity: QuantityLots::new(quantity).unwrap(),
            })),
        )
    }
    fn fill_input(sequence: u64, time: i64, fill_id: u64) -> EngineInput {
        input(
            sequence,
            time,
            CoreMessage::External(ExternalEvent::Fill(ExternalFill {
                fill_id: FillId::new(fill_id).unwrap(),
                order_id: OrderId::new(1).unwrap(),
                instrument: Instrument::BtcUsdt,
                side: Side::Buy,
                price: PriceTicks::new(100).unwrap(),
                quantity: QuantityLots::new(1).unwrap(),
            })),
        )
    }

    fn fill_for(
        sequence: u64,
        fill_id: u64,
        order_id: u64,
        side: Side,
        price: u64,
        quantity: u64,
    ) -> EngineInput {
        input(
            sequence,
            1,
            CoreMessage::External(ExternalEvent::Fill(ExternalFill {
                fill_id: FillId::new(fill_id).unwrap(),
                order_id: OrderId::new(order_id).unwrap(),
                instrument: Instrument::BtcUsdt,
                side,
                price: PriceTicks::new(price).unwrap(),
                quantity: QuantityLots::new(quantity).unwrap(),
            })),
        )
    }

    #[test]
    fn reducer_and_compatibility_wrapper_are_equivalent() {
        let inputs = [
            market_input(7, 200, 100),
            limit_order(8, 100, 1, 100, 1),
            fill_input(9, 150, 1),
        ];
        let mut state = EngineState::new(spec());
        let mut core = ExecutionCore::new(spec());
        for input in &inputs {
            let transition = reduce(&state, input).unwrap();
            state = transition.state;
            core.accept(input).unwrap();
        }
        assert_eq!(state, *core.state());
        assert_eq!(state.state_hash(), core.state_hash());
    }

    #[test]
    fn deterministic_replay_is_chunk_independent_and_preserves_effect_order() {
        let inputs = [
            market_input(7, 200, 100),
            limit_order(8, 100, 1, 100, 1),
            fill_input(9, 150, 1),
        ];
        let mut one_shot = EngineState::new(spec());
        let mut one_shot_effects = Vec::new();
        for input in &inputs {
            let transition = reduce(&one_shot, input).unwrap();
            one_shot_effects.extend_from_slice(&transition.effects);
            one_shot = transition.state;
        }
        let mut chunked = EngineState::new(spec());
        let mut chunked_effects = Vec::new();
        for chunk in inputs.chunks(2) {
            for input in chunk {
                let transition = reduce(&chunked, input).unwrap();
                chunked_effects.extend_from_slice(&transition.effects);
                chunked = transition.state;
            }
        }
        assert_eq!(one_shot, chunked);
        assert_eq!(one_shot.state_hash(), chunked.state_hash());
        assert_eq!(one_shot_effects, chunked_effects);
    }

    #[test]
    fn rejection_is_atomic_and_corrected_same_sequence_can_succeed() {
        let state = EngineState::new(spec());
        let rejected = input(
            7,
            100,
            CoreMessage::Command(OrderCommand::Submit(NewOrder {
                intent_id: IntentId::new(1).unwrap(),
                instrument: Instrument::BtcUsdt,
                side: Side::Buy,
                kind: OrderKind::Market,
                quantity: QuantityLots::new(1).unwrap(),
            })),
        );
        assert_eq!(
            reduce(&state, &rejected),
            Err(EngineError::OrderValidation {
                intent_id: IntentId::new(1).unwrap(),
                error: OrderValidationError::MissingReferencePrice
            })
        );
        assert_eq!(state.state_hash(), EngineState::new(spec()).state_hash());
        let corrected = limit_order(7, 101, 1, 100, 1);
        assert!(reduce(&state, &corrected).is_ok());
    }

    #[test]
    fn provenance_never_creates_a_second_sequence_rule_and_clock_follows_last_acceptance() {
        let state = EngineState::new(spec());
        let first = market_input(7, 200, 100);
        let mut second = market_input(8, 100, 101);
        second.source_id = SourceId::new(2).unwrap();
        second.source_seq = Some(SourceSeq::new(1));
        let state = reduce(&state, &first).unwrap().state;
        let transition = reduce(&state, &second).unwrap();
        assert_eq!(
            transition
                .state
                .virtual_clock()
                .unwrap()
                .source_event_time(),
            TimestampMicros::new(100)
        );
        assert_eq!(transition.provenance.source_seq, Some(SourceSeq::new(1)));
    }

    #[test]
    fn canonical_state_hash_has_a_fixed_v1_vector() {
        let state = EngineState::new_v1(spec());
        assert_eq!(state.canonical_bytes()[0], STATE_ENCODING_V1);
        assert_eq!(state.state_hash().get(), 2_263_100_389_333_774_488);
    }

    #[test]
    fn canonical_state_hash_has_a_fixed_populated_v2_vector() {
        let state = EngineState::new(spec());
        let state = reduce(&state, &market_input(7, 200, 100)).unwrap().state;
        let state = reduce(&state, &limit_order(8, 100, 1, 100, 1))
            .unwrap()
            .state;
        let state = reduce(&state, &fill_input(9, 150, 1)).unwrap().state;
        assert_eq!(state.canonical_bytes()[0], STATE_ENCODING_V2);
        assert_eq!(state.state_hash().get(), 16_834_929_739_150_976_491);
    }

    #[test]
    fn terminal_order_fill_is_rejected_without_a_deduplication_record() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 1, 100, 1)).unwrap();
        let order_id = core
            .order_for_intent(IntentId::new(1).unwrap())
            .unwrap()
            .id();
        core.accept(&input(
            8,
            2,
            CoreMessage::Command(OrderCommand::Cancel(CancelOrder { order_id })),
        ))
        .unwrap();
        assert_eq!(
            core.order(order_id).unwrap().status(),
            OrderStatus::Cancelled
        );
        let hash_before = core.state_hash();
        assert_eq!(
            core.accept(&fill_input(9, 3, 1)),
            Err(EngineError::OrderTransition {
                order_id,
                error: OrderTransitionError::CannotFill {
                    status: OrderStatus::Cancelled
                },
            })
        );
        assert_eq!(core.state_hash(), hash_before);
        assert_eq!(core.fill_sequence(FillId::new(1).unwrap()), None);
    }

    #[test]
    fn market_order_requires_reference_price_without_consuming_sequence() {
        let mut core = ExecutionCore::new(spec());
        let snapshot = core.clone();
        assert_eq!(
            core.accept(&market_order(7, 1, 1, 1)),
            Err(EngineError::OrderValidation {
                intent_id: IntentId::new(1).unwrap(),
                error: OrderValidationError::MissingReferencePrice
            })
        );
        assert_eq!(core, snapshot);
        core.accept(&limit_order(7, 1, 1, 100, 1)).unwrap();
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(7)));
    }

    #[test]
    fn duplicate_intent_is_atomic_and_internal_order_id_is_distinct() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 41, 100, 1)).unwrap();
        let snapshot = core.clone();
        assert_eq!(
            core.accept(&limit_order(8, 2, 41, 100, 2)),
            Err(EngineError::IntentConflict {
                intent_id: IntentId::new(41).unwrap(),
                first_sequence: EngineSeq::new(7),
                received_sequence: EngineSeq::new(8)
            })
        );
        assert_eq!(core, snapshot);
        assert_eq!(
            core.accept(&limit_order(8, 2, 41, 100, 1)),
            Err(EngineError::DuplicateIntentId {
                intent_id: IntentId::new(41).unwrap(),
                first_sequence: EngineSeq::new(7),
                received_sequence: EngineSeq::new(8)
            })
        );
        core.accept(&limit_order(8, 2, 42, 100, 1)).unwrap();
        assert_eq!(
            core.order_for_intent(IntentId::new(42).unwrap())
                .unwrap()
                .id(),
            OrderId::new(2).unwrap()
        );
    }

    #[test]
    fn sequence_gaps_and_exhaustion_are_atomic() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 1, 100, 1)).unwrap();
        assert_eq!(
            core.accept(&limit_order(9, 2, 2, 100, 1)),
            Err(EngineError::UnexpectedSequence {
                expected: EngineSeq::new(8),
                received: EngineSeq::new(9)
            })
        );
        assert_eq!(core.order_for_intent(IntentId::new(2).unwrap()), None);
        let mut max_core = ExecutionCore::new(spec());
        max_core
            .accept(&limit_order(u64::MAX, 1, 1, 100, 1))
            .unwrap();
        assert_eq!(
            max_core.accept(&limit_order(1, 2, 2, 100, 1)),
            Err(EngineError::SequenceExhausted {
                last: EngineSeq::new(u64::MAX),
                received: EngineSeq::new(1)
            })
        );
    }

    #[test]
    fn sequence_exhaustion_is_explicit_without_wraparound() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(u64::MAX, 1, 1, 100, 1)).unwrap();
        assert_eq!(
            core.accept(&limit_order(1, 2, 2, 100, 1)),
            Err(EngineError::SequenceExhausted {
                last: EngineSeq::new(u64::MAX),
                received: EngineSeq::new(1),
            })
        );
        assert_eq!(core.order_for_intent(IntentId::new(2).unwrap()), None);
    }

    #[test]
    fn market_order_uses_last_authoritative_market_price_for_min_notional() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&market_input(7, 1, 99)).unwrap();
        assert_eq!(
            core.accept(&market_order(8, 2, 1, 1)),
            Err(EngineError::OrderValidation {
                intent_id: IntentId::new(1).unwrap(),
                error: OrderValidationError::NotionalBelowMinimum {
                    minimum: UsdtAtoms::new(100),
                    received: UsdtAtoms::new(99),
                },
            })
        );
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(7)));
        core.accept(&market_input(8, 3, 100)).unwrap();
        core.accept(&market_order(9, 4, 1, 1)).unwrap();
        assert_eq!(
            core.order_for_intent(IntentId::new(1).unwrap())
                .unwrap()
                .status(),
            OrderStatus::Open
        );
    }

    #[test]
    fn source_provenance_does_not_override_engine_sequence() {
        let mut core = ExecutionCore::new(spec());
        let first = market_input(7, 200, 100);
        let mut second = market_input(8, 100, 101);
        second.source_id = SourceId::new(2).unwrap();
        second.source_seq = Some(SourceSeq::new(1));
        core.accept(&first).unwrap();
        core.accept(&second).unwrap();
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(8)));
        assert_eq!(
            core.last_market_price(Instrument::BtcUsdt),
            PriceTicks::new(101)
        );
        let mut third = market_input(9, 50, 102);
        third.source_seq = Some(SourceSeq::new(1));
        core.accept(&third).unwrap();
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(9)));
    }

    #[test]
    fn open_order_can_be_cancelled_by_internal_order_id() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 1, 100, 1)).unwrap();
        let order_id = core
            .order_for_intent(IntentId::new(1).unwrap())
            .unwrap()
            .id();
        core.accept(&input(
            8,
            2,
            CoreMessage::Command(OrderCommand::Cancel(CancelOrder { order_id })),
        ))
        .unwrap();
        assert_eq!(
            core.order(order_id).unwrap().status(),
            OrderStatus::Cancelled
        );
    }

    #[test]
    fn duplicate_fill_is_rejected_without_advancing_the_sequence() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 1, 100, 2)).unwrap();
        core.accept(&fill_input(8, 2, 1)).unwrap();
        let hash_before_rejection = core.state_hash();
        assert_eq!(
            core.accept(&fill_input(9, 3, 1)),
            Err(EngineError::DuplicateFill {
                fill_id: FillId::new(1).unwrap(),
                first_sequence: EngineSeq::new(8),
                received_sequence: EngineSeq::new(9),
            })
        );
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(8)));
        assert_eq!(core.state_hash(), hash_before_rejection);
        assert_eq!(
            core.fill_sequence(FillId::new(1).unwrap()),
            Some(EngineSeq::new(8))
        );
        core.accept(&fill_input(9, 3, 2)).unwrap();
        assert_eq!(core.last_engine_seq(), Some(EngineSeq::new(9)));
    }

    #[test]
    fn rejected_cancellation_leaves_state_and_hash_unchanged() {
        let mut core = ExecutionCore::new(spec());
        core.accept(&limit_order(7, 1, 1, 100, 1)).unwrap();
        let order_id = core
            .order_for_intent(IntentId::new(1).unwrap())
            .unwrap()
            .id();
        core.accept(&input(
            8,
            2,
            CoreMessage::Command(OrderCommand::Cancel(CancelOrder { order_id })),
        ))
        .unwrap();
        let state_before_rejection = core.state().clone();
        let hash_before_rejection = core.state_hash();
        assert_eq!(
            core.accept(&input(
                9,
                3,
                CoreMessage::Command(OrderCommand::Cancel(CancelOrder { order_id })),
            )),
            Err(EngineError::OrderTransition {
                order_id,
                error: OrderTransitionError::CannotCancel {
                    status: OrderStatus::Cancelled,
                },
            })
        );
        assert_eq!(core.state(), &state_before_rejection);
        assert_eq!(core.state_hash(), hash_before_rejection);
    }

    #[test]
    fn fills_apply_atomically_to_order_and_minimal_spot_state() {
        let mut state = EngineState::new(spec());
        state = reduce(&state, &limit_order(7, 1, 1, 100, 2)).unwrap().state;
        let partial = reduce(&state, &fill_for(8, 1, 1, Side::Buy, 100, 1)).unwrap();
        assert_eq!(
            partial
                .state
                .order(OrderId::new(1).unwrap())
                .unwrap()
                .status(),
            OrderStatus::PartiallyFilled
        );
        assert_eq!(partial.state.net_base_atoms(Instrument::BtcUsdt).get(), 1);
        assert_eq!(partial.state.quote_cash_atoms().get(), -100);
        let complete = reduce(&partial.state, &fill_for(9, 2, 1, Side::Buy, 100, 1)).unwrap();
        assert_eq!(
            complete
                .state
                .order(OrderId::new(1).unwrap())
                .unwrap()
                .status(),
            OrderStatus::Filled
        );
        assert_eq!(complete.state.net_base_atoms(Instrument::BtcUsdt).get(), 2);
        assert_eq!(complete.state.quote_cash_atoms().get(), -200);
        assert!(matches!(
            complete.effects[0],
            DomainEffect::FillApplied { .. }
        ));
    }

    #[test]
    fn invalid_fill_is_atomic_and_sell_updates_signed_spot_flow() {
        let mut state = EngineState::new(spec());
        state = reduce(&state, &limit_order(7, 1, 1, 100, 1)).unwrap().state;
        let hash = state.state_hash();
        assert_eq!(
            reduce(&state, &fill_for(8, 1, 99, Side::Buy, 100, 1)),
            Err(EngineError::UnknownOrder {
                order_id: OrderId::new(99).unwrap()
            })
        );
        assert_eq!(state.state_hash(), hash);
        let mut sell = limit_order(8, 1, 2, 100, 1);
        if let CoreMessage::Command(OrderCommand::Submit(ref mut intent)) = sell.message {
            intent.side = Side::Sell;
        }
        state = reduce(&state, &sell).unwrap().state;
        let result = reduce(&state, &fill_for(9, 2, 2, Side::Sell, 100, 1)).unwrap();
        assert_eq!(result.state.net_base_atoms(Instrument::BtcUsdt).get(), -1);
        assert_eq!(result.state.quote_cash_atoms().get(), 100);
    }
}
