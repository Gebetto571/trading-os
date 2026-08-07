//! Accepted order aggregate and deterministic lifecycle transitions.

use crate::types::{
    Instrument, InstrumentSpec, IntentId, OrderId, PriceTicks, QuantityLots, Side, UsdtAtoms,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderKind {
    Market,
    Limit { price: PriceTicks },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderStatus {
    Open,
    PartiallyFilled,
    Filled,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OrderIntent {
    pub intent_id: IntentId,
    pub instrument: Instrument,
    pub side: Side,
    pub kind: OrderKind,
    pub quantity: QuantityLots,
}

/// Compatibility name for an intent submitted to the deterministic reducer.
pub type NewOrder = OrderIntent;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CancelOrder {
    pub order_id: OrderId,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderCommand {
    Submit(NewOrder),
    Cancel(CancelOrder),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderValidationError {
    InstrumentMismatch {
        expected: Instrument,
        received: Instrument,
    },
    QuantityBelowMinimum {
        minimum: QuantityLots,
        received: QuantityLots,
    },
    MissingReferencePrice,
    NotionalBelowMinimum {
        minimum: UsdtAtoms,
        received: UsdtAtoms,
    },
    NotionalOverflow,
}

pub fn validate_intent(
    intent: &OrderIntent,
    spec: InstrumentSpec,
    reference_price: Option<PriceTicks>,
) -> Result<(), OrderValidationError> {
    if intent.instrument != spec.instrument() {
        return Err(OrderValidationError::InstrumentMismatch {
            expected: spec.instrument(),
            received: intent.instrument,
        });
    }
    if intent.quantity.get() < spec.min_quantity().get() {
        return Err(OrderValidationError::QuantityBelowMinimum {
            minimum: spec.min_quantity(),
            received: intent.quantity,
        });
    }
    let validation_price = match intent.kind {
        OrderKind::Limit { price } => price,
        OrderKind::Market => reference_price.ok_or(OrderValidationError::MissingReferencePrice)?,
    };
    let notional = spec
        .notional(validation_price, intent.quantity)
        .ok_or(OrderValidationError::NotionalOverflow)?;
    if notional.get() < spec.min_notional().get() {
        return Err(OrderValidationError::NotionalBelowMinimum {
            minimum: spec.min_notional(),
            received: notional,
        });
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Default)]
pub struct LotCount(u64);

impl LotCount {
    pub const ZERO: Self = Self(0);

    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderTransitionError {
    CannotCancel {
        status: OrderStatus,
    },
    CannotFill {
        status: OrderStatus,
    },
    FillExceedsRemaining {
        requested: QuantityLots,
        remaining: LotCount,
    },
    FilledQuantityOverflow,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Order {
    id: OrderId,
    definition: NewOrder,
    filled: LotCount,
    status: OrderStatus,
}

impl Order {
    pub(crate) const fn open(id: OrderId, definition: NewOrder) -> Self {
        Self {
            id,
            definition,
            filled: LotCount::ZERO,
            status: OrderStatus::Open,
        }
    }

    pub const fn id(&self) -> OrderId {
        self.id
    }

    pub const fn definition(&self) -> &NewOrder {
        &self.definition
    }

    pub const fn status(&self) -> OrderStatus {
        self.status
    }

    pub const fn original_quantity(&self) -> QuantityLots {
        self.definition.quantity
    }

    pub const fn filled_quantity(&self) -> LotCount {
        self.filled
    }

    pub const fn remaining_quantity(&self) -> LotCount {
        LotCount::new(self.definition.quantity.get() - self.filled.get())
    }

    pub const fn is_terminal(&self) -> bool {
        matches!(self.status, OrderStatus::Filled | OrderStatus::Cancelled)
    }

    pub(crate) fn cancel(&mut self) -> Result<(), OrderTransitionError> {
        match self.status {
            OrderStatus::Open | OrderStatus::PartiallyFilled => {
                self.status = OrderStatus::Cancelled;
                Ok(())
            }
            status => Err(OrderTransitionError::CannotCancel { status }),
        }
    }

    // Kept crate-private until ExternalFill dispatch is connected in module 4.
    #[allow(dead_code)]
    pub(crate) fn apply_fill(
        &mut self,
        quantity: QuantityLots,
    ) -> Result<(), OrderTransitionError> {
        if self.is_terminal() {
            return Err(OrderTransitionError::CannotFill {
                status: self.status,
            });
        }
        let remaining = self.remaining_quantity();
        if quantity.get() > remaining.get() {
            return Err(OrderTransitionError::FillExceedsRemaining {
                requested: quantity,
                remaining,
            });
        }

        let filled = self
            .filled
            .get()
            .checked_add(quantity.get())
            .ok_or(OrderTransitionError::FilledQuantityOverflow)?;
        self.filled = LotCount::new(filled);
        self.status = if filled == self.definition.quantity.get() {
            OrderStatus::Filled
        } else {
            OrderStatus::PartiallyFilled
        };
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn new_order(quantity: u64) -> NewOrder {
        NewOrder {
            intent_id: IntentId::new(1).unwrap(),
            instrument: Instrument::BtcUsdt,
            side: Side::Buy,
            kind: OrderKind::Limit {
                price: PriceTicks::new(100).unwrap(),
            },
            quantity: QuantityLots::new(quantity).unwrap(),
        }
    }

    #[test]
    fn accepted_order_starts_open_with_full_remaining_quantity() {
        let definition = new_order(10);
        let order = Order::open(OrderId::new(1).unwrap(), definition);

        assert_eq!(order.definition(), &definition);
        assert_eq!(order.status(), OrderStatus::Open);
        assert_eq!(order.original_quantity().get(), 10);
        assert_eq!(order.filled_quantity().get(), 0);
        assert_eq!(order.remaining_quantity().get(), 10);
        assert!(!order.is_terminal());
    }

    #[test]
    fn partial_fill_then_cancel_preserves_all_quantities() {
        let mut order = Order::open(OrderId::new(1).unwrap(), new_order(10));
        order.apply_fill(QuantityLots::new(4).unwrap()).unwrap();
        assert_eq!(order.status(), OrderStatus::PartiallyFilled);

        order.cancel().unwrap();
        assert_eq!(order.status(), OrderStatus::Cancelled);
        assert_eq!(order.original_quantity().get(), 10);
        assert_eq!(order.filled_quantity().get(), 4);
        assert_eq!(order.remaining_quantity().get(), 6);
        assert!(order.is_terminal());
    }

    #[test]
    fn complete_fill_reaches_filled_and_rejects_terminal_transitions() {
        let mut order = Order::open(OrderId::new(1).unwrap(), new_order(10));
        order.apply_fill(QuantityLots::new(10).unwrap()).unwrap();
        let snapshot = order;

        assert_eq!(order.status(), OrderStatus::Filled);
        assert_eq!(order.remaining_quantity().get(), 0);
        assert_eq!(
            order.cancel(),
            Err(OrderTransitionError::CannotCancel {
                status: OrderStatus::Filled,
            })
        );
        assert_eq!(
            order.apply_fill(QuantityLots::new(1).unwrap()),
            Err(OrderTransitionError::CannotFill {
                status: OrderStatus::Filled,
            })
        );
        assert_eq!(order, snapshot);
    }

    #[test]
    fn overfill_and_repeated_cancel_are_atomic() {
        let mut open = Order::open(OrderId::new(1).unwrap(), new_order(10));
        let open_snapshot = open;
        assert_eq!(
            open.apply_fill(QuantityLots::new(11).unwrap()),
            Err(OrderTransitionError::FillExceedsRemaining {
                requested: QuantityLots::new(11).unwrap(),
                remaining: LotCount::new(10),
            })
        );
        assert_eq!(open, open_snapshot);

        open.cancel().unwrap();
        let cancelled_snapshot = open;
        assert_eq!(
            open.cancel(),
            Err(OrderTransitionError::CannotCancel {
                status: OrderStatus::Cancelled,
            })
        );
        assert_eq!(open, cancelled_snapshot);
    }

    #[test]
    fn validates_limit_with_its_limit_price_and_market_with_reference_price() {
        let spec = InstrumentSpec::new(
            Instrument::BtcUsdt,
            UsdtAtoms::new(1),
            crate::types::BtcAtoms::new(1),
            QuantityLots::new(2).unwrap(),
            UsdtAtoms::new(100),
        )
        .unwrap();
        let limit = NewOrder {
            kind: OrderKind::Limit {
                price: PriceTicks::new(50).unwrap(),
            },
            ..new_order(2)
        };
        assert_eq!(validate_intent(&limit, spec, None), Ok(()));

        let market = NewOrder {
            kind: OrderKind::Market,
            ..limit
        };
        assert_eq!(
            validate_intent(&market, spec, None),
            Err(OrderValidationError::MissingReferencePrice)
        );
        assert_eq!(
            validate_intent(&market, spec, Some(PriceTicks::new(49).unwrap())),
            Err(OrderValidationError::NotionalBelowMinimum {
                minimum: UsdtAtoms::new(100),
                received: UsdtAtoms::new(98),
            })
        );
    }
}
