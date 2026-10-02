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
        let available_btc = self.available_btc.get().checked_sub(amount.get())?;
        let reserved_btc = self.reserved_btc.get().checked_add(amount.get())?;
        self.available_btc = BtcAtoms::new(available_btc);
        self.reserved_btc = BtcAtoms::new(reserved_btc);
        Some(())
    }
    pub(crate) fn release_btc(&mut self, amount: BtcAtoms) -> Option<()> {
        let reserved_btc = self.reserved_btc.get().checked_sub(amount.get())?;
        let available_btc = self.available_btc.get().checked_add(amount.get())?;
        self.reserved_btc = BtcAtoms::new(reserved_btc);
        self.available_btc = BtcAtoms::new(available_btc);
        Some(())
    }
    pub(crate) fn reserve_usdt(&mut self, amount: UsdtAtoms) -> Option<()> {
        let available_usdt = self.available_usdt.get().checked_sub(amount.get())?;
        let reserved_usdt = self.reserved_usdt.get().checked_add(amount.get())?;
        self.available_usdt = UsdtAtoms::new(available_usdt);
        self.reserved_usdt = UsdtAtoms::new(reserved_usdt);
        Some(())
    }
    pub(crate) fn release_usdt(&mut self, amount: UsdtAtoms) -> Option<()> {
        let reserved_usdt = self.reserved_usdt.get().checked_sub(amount.get())?;
        let available_usdt = self.available_usdt.get().checked_add(amount.get())?;
        self.reserved_usdt = UsdtAtoms::new(reserved_usdt);
        self.available_usdt = UsdtAtoms::new(available_usdt);
        Some(())
    }
    pub(crate) fn apply_buy(
        &mut self,
        base: BtcAtoms,
        cost: UsdtAtoms,
        released: UsdtAtoms,
    ) -> Option<()> {
        let reserved_cost = cost.get().checked_add(released.get())?;
        let reserved_usdt = self.reserved_usdt.get().checked_sub(reserved_cost)?;
        let available_usdt = self.available_usdt.get().checked_add(released.get())?;
        let available_btc = self.available_btc.get().checked_add(base.get())?;
        self.reserved_usdt = UsdtAtoms::new(reserved_usdt);
        self.available_usdt = UsdtAtoms::new(available_usdt);
        self.available_btc = BtcAtoms::new(available_btc);
        Some(())
    }
    pub(crate) fn apply_sell(&mut self, base: BtcAtoms, proceeds: UsdtAtoms) -> Option<()> {
        let reserved_btc = self.reserved_btc.get().checked_sub(base.get())?;
        let available_usdt = self.available_usdt.get().checked_add(proceeds.get())?;
        self.reserved_btc = BtcAtoms::new(reserved_btc);
        self.available_usdt = UsdtAtoms::new(available_usdt);
        Some(())
    }
}
