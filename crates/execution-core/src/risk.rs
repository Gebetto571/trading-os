//! Deterministic paper-spot admission limits.

use crate::types::{BtcAtoms, OrderQuantityLimit, QuantityLots, UsdtAtoms};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FundedSpotRiskLimits {
    pub max_single_order: Option<OrderQuantityLimit>,
    pub max_open_base: Option<BtcAtoms>,
    pub max_reserved_usdt: Option<UsdtAtoms>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RiskRejection {
    MarketOrderRequiresBoundedPrice,
    SingleOrderQuantityExceeded {
        maximum: OrderQuantityLimit,
        received: QuantityLots,
    },
    InsufficientAvailableBtc {
        required: BtcAtoms,
        available: BtcAtoms,
    },
    InsufficientAvailableUsdt {
        required: UsdtAtoms,
        available: UsdtAtoms,
    },
    OpenBaseLimitExceeded {
        maximum: BtcAtoms,
        requested: BtcAtoms,
    },
    ReservedUsdtLimitExceeded {
        maximum: UsdtAtoms,
        requested: UsdtAtoms,
    },
    ReservationArithmeticOverflow,
}
