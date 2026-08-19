use trading_os_execution_core::engine::{
    reduce, EngineError, EngineState, ExecutionCore, FundedSpotConfig, STATE_ENCODING_V3,
};
use trading_os_execution_core::event::{
    CoreMessage, EngineInput, ExternalEvent, ExternalFill, MarketTrade,
};
use trading_os_execution_core::order::{
    CancelOrder, NewOrder, OrderCommand, OrderKind, OrderStatus,
};
use trading_os_execution_core::portfolio::PaperPortfolioSeed;
use trading_os_execution_core::risk::{FundedSpotRiskLimits, RiskRejection};
use trading_os_execution_core::types::{
    BtcAtoms, EngineSeq, FillId, Instrument, InstrumentSpec, IntentId, OrderId, OrderQuantityLimit,
    PriceTicks, QuantityLots, Side, SourceId, TimestampMicros, UsdtAtoms,
};

fn spec() -> InstrumentSpec {
    InstrumentSpec::new(
        Instrument::BtcUsdt,
        UsdtAtoms::new(1),
        BtcAtoms::new(1),
        QuantityLots::new(1).unwrap(),
        UsdtAtoms::new(1),
    )
    .unwrap()
}

fn input(sequence: u64, message: CoreMessage) -> EngineInput {
    EngineInput {
        engine_seq: EngineSeq::new(sequence),
        source_id: SourceId::new(1).unwrap(),
        source_seq: None,
        source_event_time: TimestampMicros::new(1),
        message,
    }
}

fn submit(sequence: u64, side: Side, quantity: u64) -> EngineInput {
    input(
        sequence,
        CoreMessage::Command(OrderCommand::Submit(NewOrder {
            intent_id: IntentId::new(sequence).unwrap(),
            instrument: Instrument::BtcUsdt,
            side,
            kind: OrderKind::Limit {
                price: PriceTicks::new(100).unwrap(),
            },
            quantity: QuantityLots::new(quantity).unwrap(),
        })),
    )
}

fn fill(sequence: u64, side: Side, quantity: u64) -> EngineInput {
    input(
        sequence,
        CoreMessage::External(ExternalEvent::Fill(ExternalFill {
            fill_id: FillId::new(sequence).unwrap(),
            order_id: OrderId::new(1).unwrap(),
            instrument: Instrument::BtcUsdt,
            side,
            price: PriceTicks::new(100).unwrap(),
            quantity: QuantityLots::new(quantity).unwrap(),
        })),
    )
}

#[test]
fn spot_order_vocabulary_covers_the_scaffold_scope() {
    let intent_id = IntentId::new(1).unwrap();
    let order_id = OrderId::new(1).unwrap();
    let quantity = QuantityLots::new(2).unwrap();
    let market = NewOrder {
        intent_id,
        instrument: Instrument::BtcUsdt,
        side: Side::Buy,
        kind: OrderKind::Market,
        quantity,
    };
    let limit = NewOrder {
        kind: OrderKind::Limit {
            price: PriceTicks::new(3).unwrap(),
        },
        ..market
    };

    assert!(matches!(
        OrderCommand::Submit(market),
        OrderCommand::Submit(_)
    ));
    assert!(matches!(
        OrderCommand::Submit(limit),
        OrderCommand::Submit(_)
    ));
    assert!(matches!(
        OrderCommand::Cancel(CancelOrder { order_id }),
        OrderCommand::Cancel(_)
    ));
    assert_eq!(OrderStatus::Open, OrderStatus::Open);
}

#[test]
fn integer_domain_types_accept_their_maximum_values() {
    assert_eq!(PriceTicks::new(u64::MAX).unwrap().get(), u64::MAX);
    assert_eq!(QuantityLots::new(u64::MAX).unwrap().get(), u64::MAX);
    assert_eq!(OrderId::new(u64::MAX).unwrap().get(), u64::MAX);
    assert_eq!(IntentId::new(u64::MAX).unwrap().get(), u64::MAX);
    assert_eq!(FillId::new(u64::MAX).unwrap().get(), u64::MAX);
}

#[test]
fn external_fill_carries_a_required_identity() {
    let fill = ExternalFill {
        fill_id: FillId::new(11).unwrap(),
        order_id: OrderId::new(7).unwrap(),
        instrument: Instrument::BtcUsdt,
        side: Side::Buy,
        price: PriceTicks::new(100).unwrap(),
        quantity: QuantityLots::new(2).unwrap(),
    };

    assert_eq!(fill.fill_id.get(), 11);
}

#[test]
fn mismatched_fill_side_is_atomic_and_correctable_at_the_same_sequence() {
    let state = reduce(&EngineState::new(spec()), &submit(7, Side::Buy, 2))
        .unwrap()
        .state;
    let before = state.clone();
    let hash_before = state.state_hash();
    assert_eq!(
        reduce(&state, &fill(8, Side::Sell, 1)),
        Err(EngineError::FillSideMismatch {
            order_id: OrderId::new(1).unwrap(),
            expected: Side::Buy,
            received: Side::Sell,
        })
    );
    assert_eq!(state, before);
    assert_eq!(state.state_hash(), hash_before);
    let corrected = reduce(&state, &fill(8, Side::Buy, 1)).unwrap();
    assert_eq!(corrected.effects.len(), 3);
}

#[test]
fn overfill_is_atomic_and_correctable_at_the_same_sequence() {
    let state = reduce(&EngineState::new(spec()), &submit(7, Side::Buy, 1))
        .unwrap()
        .state;
    let before = state.clone();
    let hash_before = state.state_hash();
    assert!(matches!(
        reduce(&state, &fill(8, Side::Buy, 2)),
        Err(EngineError::OrderTransition { .. })
    ));
    assert_eq!(state, before);
    assert_eq!(state.state_hash(), hash_before);
    let corrected = reduce(&state, &fill(8, Side::Buy, 1)).unwrap();
    assert_eq!(corrected.effects.len(), 3);
}

#[test]
fn duplicate_intent_and_fill_are_fail_closed_without_changing_canonical_state() {
    let submitted = reduce(
        &EngineState::new(spec()),
        &submit_limit(1, 1, Side::Buy, 100, 1),
    )
    .unwrap()
    .state;
    let submitted_before = submitted.clone();
    let submitted_bytes = submitted.canonical_bytes();
    let submitted_hash = submitted.state_hash();
    assert!(matches!(
        reduce(&submitted, &submit_limit(2, 1, Side::Buy, 100, 1)),
        Err(EngineError::DuplicateIntentId { .. })
    ));
    assert_eq!(submitted, submitted_before);
    assert_eq!(submitted.canonical_bytes(), submitted_bytes);
    assert_eq!(submitted.state_hash(), submitted_hash);

    let filled = reduce(&submitted, &fill_order(2, 9, 1, Side::Buy, 100, 1))
        .unwrap()
        .state;
    let filled_before = filled.clone();
    let filled_bytes = filled.canonical_bytes();
    let filled_hash = filled.state_hash();
    assert!(matches!(
        reduce(&filled, &fill_order(3, 9, 1, Side::Buy, 100, 1)),
        Err(EngineError::DuplicateFill { .. })
    ));
    assert_eq!(filled, filled_before);
    assert_eq!(filled.canonical_bytes(), filled_bytes);
    assert_eq!(filled.state_hash(), filled_hash);
}

fn funded_state() -> EngineState {
    funded_state_with(0, 200, limits(Some(2), Some(2), Some(200)))
}

fn limits(
    max_single_order: Option<u64>,
    max_open_base: Option<u128>,
    max_reserved_usdt: Option<u128>,
) -> FundedSpotRiskLimits {
    FundedSpotRiskLimits {
        max_single_order: max_single_order.map(OrderQuantityLimit::new),
        max_open_base: max_open_base.map(BtcAtoms::new),
        max_reserved_usdt: max_reserved_usdt.map(UsdtAtoms::new),
    }
}

fn funded_state_with(btc: u128, usdt: u128, limits: FundedSpotRiskLimits) -> EngineState {
    EngineState::new_funded_spot(
        spec(),
        FundedSpotConfig {
            seed: PaperPortfolioSeed {
                btc: BtcAtoms::new(btc),
                usdt: UsdtAtoms::new(usdt),
            },
            limits,
        },
    )
}

fn submit_limit(
    sequence: u64,
    intent_id: u64,
    side: Side,
    price: u64,
    quantity: u64,
) -> EngineInput {
    input(
        sequence,
        CoreMessage::Command(OrderCommand::Submit(NewOrder {
            intent_id: IntentId::new(intent_id).unwrap(),
            instrument: Instrument::BtcUsdt,
            side,
            kind: OrderKind::Limit {
                price: PriceTicks::new(price).unwrap(),
            },
            quantity: QuantityLots::new(quantity).unwrap(),
        })),
    )
}

fn fill_order(
    sequence: u64,
    fill_id: u64,
    order_id: u64,
    side: Side,
    price: u64,
    quantity: u64,
) -> EngineInput {
    input(
        sequence,
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

fn hex_bytes(value: &str) -> Vec<u8> {
    assert_eq!(value.len() % 2, 0);
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let decode = |byte| match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                _ => panic!("invalid hexadecimal test vector"),
            };
            (decode(pair[0]) << 4) | decode(pair[1])
        })
        .collect()
}

fn assert_atomic_risk_reject(state: &EngineState, rejected: &EngineInput, expected: RiskRejection) {
    let before = state.clone();
    let bytes = state.canonical_bytes();
    let hash = state.state_hash();
    assert_eq!(
        reduce(state, rejected),
        Err(EngineError::RiskReject(expected))
    );
    assert_eq!(state, &before);
    assert_eq!(state.canonical_bytes(), bytes);
    assert_eq!(state.state_hash(), hash);
}

#[test]
fn funded_long_only_buy_reserves_then_releases_price_improvement_atomically() {
    let submitted = reduce(&funded_state(), &submit(1, Side::Buy, 1))
        .unwrap()
        .state;
    assert_eq!(submitted.encoding_version(), STATE_ENCODING_V3);
    let before_fill = submitted.funded_spot_portfolio().unwrap();
    assert_eq!(before_fill.available_usdt().get(), 100);
    assert_eq!(before_fill.reserved_usdt().get(), 100);

    let filled = reduce(
        &submitted,
        &input(
            2,
            CoreMessage::External(ExternalEvent::Fill(ExternalFill {
                fill_id: FillId::new(2).unwrap(),
                order_id: OrderId::new(1).unwrap(),
                instrument: Instrument::BtcUsdt,
                side: Side::Buy,
                price: PriceTicks::new(90).unwrap(),
                quantity: QuantityLots::new(1).unwrap(),
            })),
        ),
    )
    .unwrap()
    .state;
    let portfolio = filled.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_btc().get(), 1);
    assert_eq!(portfolio.reserved_usdt().get(), 0);
    assert_eq!(portfolio.available_usdt().get(), 110);
}

#[test]
fn funded_long_only_rejections_are_atomic_and_same_sequence_is_correctable() {
    let state = funded_state();
    let hash = state.state_hash();
    assert_eq!(
        reduce(&state, &submit(1, Side::Sell, 1)),
        Err(EngineError::RiskReject(
            RiskRejection::InsufficientAvailableBtc {
                required: BtcAtoms::new(1),
                available: BtcAtoms::new(0),
            }
        ))
    );
    assert_eq!(state.state_hash(), hash);
    let accepted = reduce(&state, &submit(1, Side::Buy, 1)).unwrap();
    assert_eq!(accepted.state.last_engine_seq(), Some(EngineSeq::new(1)));
}

#[test]
fn v3_golden_vector_covers_seed_balances_and_optional_limit_tags() {
    // This literal vector fixes the V3 funded-profile tag, seed, four balance
    // buckets, and a mixed Some(0)/None optional-limit encoding.
    let fresh = funded_state_with(3, 7, limits(Some(0), None, Some(0)));
    let fresh_bytes = hex_bytes(
        "0301000000000000000000000000000000010000000000000000000000000000000100000000000000010000000000000000000000000000000100000001000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000030000000000000000000000000000000701000000000000000000010000000000000000000000000000000000000000000000000000000000000003000000000000000000000000000000000000000000000000000000000000000700000000000000000000000000000000",
    );
    assert_eq!(fresh.encoding_version(), STATE_ENCODING_V3);
    assert_eq!(fresh.canonical_bytes(), fresh_bytes);
    assert_eq!(fresh.state_hash().get(), 0x0170_aebd_12d2_5c88);

    let none = funded_state_with(3, 7, limits(None, None, None));
    assert_ne!(fresh.canonical_bytes(), none.canonical_bytes());
    assert_ne!(fresh.state_hash(), none.state_hash());

    let partial = reduce(
        &funded_state_with(5, 500, limits(None, None, None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .unwrap()
    .state;
    let partial = reduce(&partial, &fill_order(2, 2, 1, Side::Buy, 90, 1))
        .unwrap()
        .state;
    let partial_bytes = hex_bytes(
        "030100000000000000000000000000000001000000000000000000000000000000010000000000000001000000000000000000000000000000010100000000000000020100000000000000020000000000000001000000000000000001010000000000000001010000000000000002000000000000000000000000000000010000000000000002000000000000000200000000000000000000000000000001000000000000000100000000000000010000000000000001010102000000000000006400000000000000020000000000000001020000000000000000000000000000000100000000000000010000000000000001000000000000000100000000000000010101020000000000000064000000000000000200000000000000000000000000000000000000000000000000000000000000010100000000000000000000000000000001ffffffffffffffffffffffffffffffa60100000000000000000000000000000005000000000000000000000000000001f400000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000013600000000000000000000000000000064",
    );
    assert_eq!(partial.canonical_bytes(), partial_bytes);
    assert_eq!(partial.state_hash().get(), 0x73a4_84d8_1139_941d);
}

#[test]
fn funded_cancel_releases_only_its_remaining_reservation() {
    let state = funded_state_with(0, 300, limits(None, None, None));
    let state = reduce(&state, &submit_limit(1, 1, Side::Buy, 100, 2))
        .unwrap()
        .state;
    let state = reduce(&state, &submit_limit(2, 2, Side::Buy, 100, 1))
        .unwrap()
        .state;
    let cancelled = reduce(
        &state,
        &input(
            3,
            CoreMessage::Command(OrderCommand::Cancel(CancelOrder {
                order_id: OrderId::new(1).unwrap(),
            })),
        ),
    )
    .unwrap();
    let portfolio = cancelled.state.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_usdt().get(), 200);
    assert_eq!(portfolio.reserved_usdt().get(), 100);
    assert_eq!(
        cancelled
            .state
            .order(OrderId::new(1).unwrap())
            .unwrap()
            .status(),
        OrderStatus::Cancelled
    );
    assert_eq!(
        cancelled
            .state
            .order(OrderId::new(2).unwrap())
            .unwrap()
            .remaining_quantity()
            .get(),
        1
    );
    assert_eq!(cancelled.effects.len(), 1);
}

#[test]
fn funded_sell_fill_consumes_only_filled_btc_reservation_and_preserves_signed_flow() {
    let state = funded_state_with(3, 0, limits(None, None, None));
    let state = reduce(&state, &submit_limit(1, 1, Side::Sell, 100, 2))
        .unwrap()
        .state;
    let partial = reduce(&state, &fill_order(2, 2, 1, Side::Sell, 110, 1)).unwrap();
    let portfolio = partial.state.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_btc().get(), 1);
    assert_eq!(portfolio.reserved_btc().get(), 1);
    assert_eq!(portfolio.available_usdt().get(), 110);
    assert_eq!(partial.state.net_base_atoms(Instrument::BtcUsdt).get(), -1);
    assert_eq!(partial.state.quote_cash_atoms().get(), 110);

    let complete = reduce(&partial.state, &fill_order(3, 3, 1, Side::Sell, 110, 1)).unwrap();
    let portfolio = complete.state.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.reserved_btc().get(), 0);
    assert_eq!(portfolio.available_usdt().get(), 220);
    assert_eq!(complete.state.net_base_atoms(Instrument::BtcUsdt).get(), -2);
    assert_eq!(complete.state.quote_cash_atoms().get(), 220);
}

#[test]
fn funded_risk_limits_are_typed_atomic_and_correctable() {
    let single = funded_state_with(0, 500, limits(Some(1), None, None));
    assert_atomic_risk_reject(
        &single,
        &submit_limit(1, 1, Side::Buy, 100, 2),
        RiskRejection::SingleOrderQuantityExceeded {
            maximum: OrderQuantityLimit::new(1),
            received: QuantityLots::new(2).unwrap(),
        },
    );
    assert!(reduce(&single, &submit_limit(1, 1, Side::Buy, 100, 1)).is_ok());

    let open = funded_state_with(10, 500, limits(None, Some(1), None));
    assert_atomic_risk_reject(
        &open,
        &submit_limit(1, 1, Side::Buy, 100, 2),
        RiskRejection::OpenBaseLimitExceeded {
            maximum: BtcAtoms::new(1),
            requested: BtcAtoms::new(2),
        },
    );
    // Initial BTC is not open-buy exposure: the corrected one-lot order fits.
    assert!(reduce(&open, &submit_limit(1, 1, Side::Buy, 100, 1)).is_ok());

    let reserved = funded_state_with(0, 500, limits(None, None, Some(100)));
    assert_atomic_risk_reject(
        &reserved,
        &submit_limit(1, 1, Side::Buy, 100, 2),
        RiskRejection::ReservedUsdtLimitExceeded {
            maximum: UsdtAtoms::new(100),
            requested: UsdtAtoms::new(200),
        },
    );
    assert!(reduce(&reserved, &submit_limit(1, 1, Side::Buy, 100, 1)).is_ok());
}

#[test]
fn optional_risk_limit_boundaries_distinguish_none_zero_exact_and_one_over() {
    assert!(reduce(
        &funded_state_with(0, 500, limits(None, None, None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .is_ok());
    assert!(matches!(
        reduce(
            &funded_state_with(0, 500, limits(Some(0), None, None)),
            &submit_limit(1, 1, Side::Buy, 100, 1),
        ),
        Err(EngineError::RiskReject(
            RiskRejection::SingleOrderQuantityExceeded { .. }
        ))
    ));
    assert!(reduce(
        &funded_state_with(0, 500, limits(Some(2), None, None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .is_ok());

    assert!(matches!(
        reduce(
            &funded_state_with(0, 500, limits(None, Some(0), None)),
            &submit_limit(1, 1, Side::Buy, 100, 1),
        ),
        Err(EngineError::RiskReject(
            RiskRejection::OpenBaseLimitExceeded { .. }
        ))
    ));
    assert!(reduce(
        &funded_state_with(0, 500, limits(None, Some(2), None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .is_ok());

    assert!(matches!(
        reduce(
            &funded_state_with(0, 500, limits(None, None, Some(0))),
            &submit_limit(1, 1, Side::Buy, 100, 1),
        ),
        Err(EngineError::RiskReject(
            RiskRejection::ReservedUsdtLimitExceeded { .. }
        ))
    ));
    assert!(reduce(
        &funded_state_with(0, 500, limits(None, None, Some(200))),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .is_ok());
}

#[test]
fn funded_reducer_and_wrapper_replay_match() {
    let config = FundedSpotConfig {
        seed: PaperPortfolioSeed {
            btc: BtcAtoms::new(3),
            usdt: UsdtAtoms::new(500),
        },
        limits: limits(None, None, None),
    };
    let inputs = [
        submit_limit(1, 1, Side::Buy, 100, 1),
        fill_order(2, 2, 1, Side::Buy, 90, 1),
        submit_limit(3, 3, Side::Sell, 100, 1),
        fill_order(4, 4, 2, Side::Sell, 100, 1),
    ];
    let mut pure = EngineState::new_funded_spot(spec(), config);
    let mut effects = Vec::new();
    for value in &inputs {
        let transition = reduce(&pure, value).unwrap();
        effects.extend_from_slice(&transition.effects);
        pure = transition.state;
    }
    let mut wrapper = ExecutionCore::new_funded_spot(spec(), config);
    for value in &inputs {
        wrapper.accept(value).unwrap();
    }
    assert_eq!(wrapper.state(), &pure);
    assert_eq!(wrapper.state_hash(), pure.state_hash());
    assert_eq!(effects.len(), 8);
}

#[test]
fn funded_exact_cash_and_reservation_lifecycle_are_conserved() {
    let exact = reduce(
        &funded_state_with(0, 200, limits(None, None, None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .unwrap()
    .state;
    let portfolio = exact.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_usdt().get(), 0);
    assert_eq!(portfolio.reserved_usdt().get(), 200);

    let insufficient = funded_state_with(0, 199, limits(None, None, None));
    assert_atomic_risk_reject(
        &insufficient,
        &submit_limit(1, 1, Side::Buy, 100, 2),
        RiskRejection::InsufficientAvailableUsdt {
            required: UsdtAtoms::new(200),
            available: UsdtAtoms::new(199),
        },
    );

    let partial = reduce(
        &funded_state_with(0, 300, limits(None, None, None)),
        &submit_limit(1, 1, Side::Buy, 100, 2),
    )
    .unwrap()
    .state;
    let partial = reduce(&partial, &fill_order(2, 2, 1, Side::Buy, 90, 1))
        .unwrap()
        .state;
    let cancelled = reduce(
        &partial,
        &input(
            3,
            CoreMessage::Command(OrderCommand::Cancel(CancelOrder {
                order_id: OrderId::new(1).unwrap(),
            })),
        ),
    )
    .unwrap()
    .state;
    let portfolio = cancelled.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_usdt().get(), 210);
    assert_eq!(portfolio.reserved_usdt().get(), 0);
    assert_eq!(portfolio.available_btc().get(), 1);
}

#[test]
fn funded_market_buy_is_rejected_while_market_sell_reserves_base() {
    let state = reduce(
        &funded_state_with(2, 500, limits(None, None, None)),
        &input(
            1,
            CoreMessage::External(ExternalEvent::MarketTrade(MarketTrade {
                instrument: Instrument::BtcUsdt,
                price: PriceTicks::new(100).unwrap(),
                quantity: QuantityLots::new(1).unwrap(),
            })),
        ),
    )
    .unwrap()
    .state;
    let market_buy = input(
        2,
        CoreMessage::Command(OrderCommand::Submit(NewOrder {
            intent_id: IntentId::new(2).unwrap(),
            instrument: Instrument::BtcUsdt,
            side: Side::Buy,
            kind: OrderKind::Market,
            quantity: QuantityLots::new(1).unwrap(),
        })),
    );
    assert_atomic_risk_reject(
        &state,
        &market_buy,
        RiskRejection::MarketOrderRequiresBoundedPrice,
    );

    let market_sell = input(
        2,
        CoreMessage::Command(OrderCommand::Submit(NewOrder {
            intent_id: IntentId::new(3).unwrap(),
            instrument: Instrument::BtcUsdt,
            side: Side::Sell,
            kind: OrderKind::Market,
            quantity: QuantityLots::new(1).unwrap(),
        })),
    );
    let accepted = reduce(&state, &market_sell).unwrap().state;
    let portfolio = accepted.funded_spot_portfolio().unwrap();
    assert_eq!(portfolio.available_btc().get(), 1);
    assert_eq!(portfolio.reserved_btc().get(), 1);
}
