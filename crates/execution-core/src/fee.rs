//! Replaceable fee calculation policy.

use crate::event::ExternalFill;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Default)]
pub struct FeeUnits(u128);

impl FeeUnits {
    pub const ZERO: Self = Self(0);

    pub const fn new(value: u128) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u128 {
        self.0
    }
}

pub trait FeePolicy {
    fn fee_for(&self, fill: &ExternalFill) -> FeeUnits;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct ZeroFee;

impl FeePolicy for ZeroFee {
    fn fee_for(&self, _fill: &ExternalFill) -> FeeUnits {
        FeeUnits::ZERO
    }
}
