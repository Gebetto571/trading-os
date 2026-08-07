//! Strong primitive types used by the execution core.

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Instrument {
    BtcUsdt,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Side {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PriceTicks(u64);

impl PriceTicks {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct QuantityLots(u64);

impl QuantityLots {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

/// A risk-policy quantity threshold. Unlike an executable order quantity,
/// zero is meaningful here: it disables every positive-sized order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OrderQuantityLimit(u64);

impl OrderQuantityLimit {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct UsdtAtoms(u128);

impl UsdtAtoms {
    pub const ZERO: Self = Self(0);

    pub const fn new(value: u128) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u128 {
        self.0
    }
}

/// BTC atomic units. This is deliberately distinct from quote-asset USDT atoms.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct BtcAtoms(u128);

impl BtcAtoms {
    pub const ZERO: Self = Self(0);

    pub const fn new(value: u128) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u128 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OrderId(u64);

impl OrderId {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct IntentId(u64);

impl IntentId {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FillId(u64);

impl FillId {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EngineSeq(u64);

impl EngineSeq {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }

    pub const fn checked_next(self) -> Option<Self> {
        match self.0.checked_add(1) {
            Some(value) => Some(Self(value)),
            None => None,
        }
    }
}

/// Backward-compatible name for the reducer's canonical sequence.
pub type EventSequence = EngineSeq;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SourceId(u64);

impl SourceId {
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 {
            None
        } else {
            Some(Self(value))
        }
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SourceSeq(u64);

impl SourceSeq {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TimestampMicros(i64);

impl TimestampMicros {
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> i64 {
        self.0
    }
}

/// The source timestamp of the most recently accepted input.
///
/// This is a reducer-owned virtual clock, not a wall clock. It intentionally
/// permits moving backwards because source timestamps are provenance and do
/// not participate in canonical engine sequencing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct VirtualClock(TimestampMicros);

impl VirtualClock {
    pub const fn from_source_event_time(value: TimestampMicros) -> Self {
        Self(value)
    }

    pub const fn source_event_time(self) -> TimestampMicros {
        self.0
    }
}

/// A deterministic, non-cryptographic fingerprint of canonical engine state.
///
/// It is useful for replay equivalence checks only; it is neither a signature
/// nor a security boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StateHash(u64);

impl StateHash {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Signed net BTC inventory for the minimal spot view. Negative values are
/// permitted because this slice has no opening-balance or availability policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SignedBtcAtoms(i128);

impl SignedBtcAtoms {
    pub const ZERO: Self = Self(0);
    pub const fn get(self) -> i128 {
        self.0
    }
    pub fn from_atoms(value: BtcAtoms) -> Option<Self> {
        match i128::try_from(value.get()) {
            Ok(value) => Some(Self(value)),
            Err(_) => None,
        }
    }
    pub const fn checked_add(self, value: i128) -> Option<Self> {
        match self.0.checked_add(value) {
            Some(value) => Some(Self(value)),
            None => None,
        }
    }
}

/// Signed USDT cash movement for the minimal spot view.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SignedUsdtAtoms(i128);

impl SignedUsdtAtoms {
    pub const ZERO: Self = Self(0);
    pub const fn get(self) -> i128 {
        self.0
    }
    pub fn from_atoms(value: UsdtAtoms) -> Option<Self> {
        match i128::try_from(value.get()) {
            Ok(value) => Some(Self(value)),
            Err(_) => None,
        }
    }
    pub const fn checked_add(self, value: i128) -> Option<Self> {
        match self.0.checked_add(value) {
            Some(value) => Some(Self(value)),
            None => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InstrumentSpec {
    instrument: Instrument,
    /// USDT atoms represented by one price tick for one quantity lot.
    tick_size: UsdtAtoms,
    /// BTC atoms represented by one quantity lot.
    lot_size: BtcAtoms,
    min_quantity: QuantityLots,
    /// A zero value explicitly means that this instrument has no minimum notional.
    min_notional: UsdtAtoms,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InstrumentSpecError {
    ZeroTickSize,
    ZeroLotSize,
}

impl InstrumentSpec {
    pub const fn new(
        instrument: Instrument,
        tick_size: UsdtAtoms,
        lot_size: BtcAtoms,
        min_quantity: QuantityLots,
        min_notional: UsdtAtoms,
    ) -> Result<Self, InstrumentSpecError> {
        if tick_size.get() == 0 {
            Err(InstrumentSpecError::ZeroTickSize)
        } else if lot_size.get() == 0 {
            Err(InstrumentSpecError::ZeroLotSize)
        } else {
            Ok(Self {
                instrument,
                tick_size,
                lot_size,
                min_quantity,
                min_notional,
            })
        }
    }

    pub const fn instrument(&self) -> Instrument {
        self.instrument
    }

    pub const fn tick_size(&self) -> UsdtAtoms {
        self.tick_size
    }

    pub const fn lot_size(&self) -> BtcAtoms {
        self.lot_size
    }

    pub const fn min_quantity(&self) -> QuantityLots {
        self.min_quantity
    }

    pub const fn min_notional(&self) -> UsdtAtoms {
        self.min_notional
    }

    /// Converts tick and lot counts to USDT through this validated instrument scale.
    /// `tick_size` is denominated in USDT atoms per quantity lot; `lot_size`
    /// records the BTC amount represented by that lot.
    pub fn notional(&self, price: PriceTicks, quantity: QuantityLots) -> Option<UsdtAtoms> {
        u128::from(price.get())
            .checked_mul(u128::from(quantity.get()))
            .and_then(|value| value.checked_mul(self.tick_size.get()))
            .map(UsdtAtoms::new)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn price_quantity_and_ids_must_be_positive() {
        assert_eq!(PriceTicks::new(0), None);
        assert_eq!(QuantityLots::new(0), None);
        assert_eq!(OrderId::new(0), None);
        assert_eq!(IntentId::new(0), None);
        assert_eq!(FillId::new(0), None);
        assert_eq!(SourceId::new(0), None);
        assert_eq!(PriceTicks::new(1).map(PriceTicks::get), Some(1));
        assert_eq!(QuantityLots::new(1).map(QuantityLots::get), Some(1));
        assert_eq!(OrderId::new(1).map(OrderId::get), Some(1));
        assert_eq!(IntentId::new(1).map(IntentId::get), Some(1));
        assert_eq!(FillId::new(1).map(FillId::get), Some(1));
        assert_eq!(SourceId::new(1).map(SourceId::get), Some(1));
    }

    #[test]
    fn event_sequence_reports_exhaustion_without_overflow() {
        assert_eq!(EngineSeq::new(7).checked_next(), Some(EngineSeq::new(8)));
        assert_eq!(EngineSeq::new(u64::MAX).checked_next(), None);
    }

    #[test]
    fn notional_uses_checked_integer_arithmetic() {
        let spec = InstrumentSpec::new(
            Instrument::BtcUsdt,
            UsdtAtoms::new(100),
            BtcAtoms::new(1),
            QuantityLots::new(1).unwrap(),
            UsdtAtoms::new(1),
        )
        .unwrap();
        assert_eq!(
            spec.notional(PriceTicks::new(3).unwrap(), QuantityLots::new(2).unwrap()),
            Some(UsdtAtoms::new(600))
        );
        assert_eq!(
            spec.notional(
                PriceTicks::new(u64::MAX).unwrap(),
                QuantityLots::new(u64::MAX).unwrap(),
            ),
            None
        );
    }

    #[test]
    fn instrument_spec_rejects_zero_tick_and_lot_sizes() {
        assert_eq!(
            InstrumentSpec::new(
                Instrument::BtcUsdt,
                UsdtAtoms::ZERO,
                BtcAtoms::new(1),
                QuantityLots::new(1).unwrap(),
                UsdtAtoms::ZERO,
            ),
            Err(InstrumentSpecError::ZeroTickSize)
        );
        assert_eq!(
            InstrumentSpec::new(
                Instrument::BtcUsdt,
                UsdtAtoms::new(1),
                BtcAtoms::ZERO,
                QuantityLots::new(1).unwrap(),
                UsdtAtoms::ZERO,
            ),
            Err(InstrumentSpecError::ZeroLotSize)
        );
    }

    #[test]
    fn instrument_spec_exposes_explicit_btc_and_usdt_scales() {
        let spec = InstrumentSpec::new(
            Instrument::BtcUsdt,
            UsdtAtoms::new(25),
            BtcAtoms::new(10_000),
            QuantityLots::new(2).unwrap(),
            UsdtAtoms::ZERO,
        )
        .unwrap();
        assert_eq!(spec.tick_size(), UsdtAtoms::new(25));
        assert_eq!(spec.lot_size(), BtcAtoms::new(10_000));
        assert_eq!(
            spec.notional(PriceTicks::new(3).unwrap(), QuantityLots::new(2).unwrap()),
            Some(UsdtAtoms::new(150))
        );
    }
}
