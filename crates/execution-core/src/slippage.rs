//! Replaceable slippage measurement policy.
//!
//! The authoritative fill price is never changed here. A simulator may use the
//! reported measurement, but the execution core only consumes external fills.

use crate::event::ExternalFill;
use crate::types::PriceTicks;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SlippageTicks(i128);

impl SlippageTicks {
    pub const ZERO: Self = Self(0);

    pub const fn new(value: i128) -> Self {
        Self(value)
    }

    pub const fn get(self) -> i128 {
        self.0
    }
}

pub trait SlippagePolicy {
    fn measure(&self, fill: &ExternalFill, reference_price: PriceTicks) -> SlippageTicks;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct ZeroSlippage;

impl SlippagePolicy for ZeroSlippage {
    fn measure(&self, _fill: &ExternalFill, _reference_price: PriceTicks) -> SlippageTicks {
        SlippageTicks::ZERO
    }
}
