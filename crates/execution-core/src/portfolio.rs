//! Minimal funded paper-spot portfolio.
//!
//! This is deliberately a balance and reservation model, not a P&L model.

use crate::types::{BtcAtoms, UsdtAtoms};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PaperPortfolioSeed {
    pub btc: BtcAtoms,
    pub usdt: UsdtAtoms,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FundedSpotPortfolio {
    available_btc: BtcAtoms,
    reserved_btc: BtcAtoms,
    available_usdt: UsdtAtoms,
    reserved_usdt: UsdtAtoms,
}

impl FundedSpotPortfolio {
    pub const fn from_seed(seed: PaperPortfolioSeed) -> Self {
        Self {
            available_btc: seed.btc,
            reserved_btc: BtcAtoms::ZERO,
            available_usdt: seed.usdt,
            reserved_usdt: UsdtAtoms::ZERO,
        }
    }

    pub const fn available_btc(&self) -> BtcAtoms {
        self.available_btc
    }
    pub const fn reserved_btc(&self) -> BtcAtoms {
        self.reserved_btc
    }
    pub const fn available_usdt(&self) -> UsdtAtoms {
        self.available_usdt
    }
    pub const fn reserved_usdt(&self) -> UsdtAtoms {
        self.reserved_usdt
    }

    pub(crate) fn reserve_btc(&mut self, amount: BtcAtoms) -> Option<()> {
        self.available_btc = BtcAtoms::new(self.available_btc.get().checked_sub(amount.get())?);
        self.reserved_btc = BtcAtoms::new(self.reserved_btc.get().checked_add(amount.get())?);
        Some(())
    }
    pub(crate) fn release_btc(&mut self, amount: BtcAtoms) -> Option<()> {
        self.reserved_btc = BtcAtoms::new(self.reserved_btc.get().checked_sub(amount.get())?);
        self.available_btc = BtcAtoms::new(self.available_btc.get().checked_add(amount.get())?);
        Some(())
    }
    pub(crate) fn reserve_usdt(&mut self, amount: UsdtAtoms) -> Option<()> {
        self.available_usdt = UsdtAtoms::new(self.available_usdt.get().checked_sub(amount.get())?);
        self.reserved_usdt = UsdtAtoms::new(self.reserved_usdt.get().checked_add(amount.get())?);
        Some(())
    }
    pub(crate) fn release_usdt(&mut self, amount: UsdtAtoms) -> Option<()> {
        self.reserved_usdt = UsdtAtoms::new(self.reserved_usdt.get().checked_sub(amount.get())?);
        self.available_usdt = UsdtAtoms::new(self.available_usdt.get().checked_add(amount.get())?);
        Some(())
    }
    pub(crate) fn apply_buy(
        &mut self,
        base: BtcAtoms,
        cost: UsdtAtoms,
        released: UsdtAtoms,
    ) -> Option<()> {
        self.reserved_usdt = UsdtAtoms::new(
            self.reserved_usdt
                .get()
                .checked_sub(cost.get().checked_add(released.get())?)?,
        );
        self.available_usdt =
            UsdtAtoms::new(self.available_usdt.get().checked_add(released.get())?);
        self.available_btc = BtcAtoms::new(self.available_btc.get().checked_add(base.get())?);
        Some(())
    }
    pub(crate) fn apply_sell(&mut self, base: BtcAtoms, proceeds: UsdtAtoms) -> Option<()> {
        self.reserved_btc = BtcAtoms::new(self.reserved_btc.get().checked_sub(base.get())?);
        self.available_usdt =
            UsdtAtoms::new(self.available_usdt.get().checked_add(proceeds.get())?);
        Some(())
    }
}
