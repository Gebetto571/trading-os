#![forbid(unsafe_code)]

//! Deterministic, simulation-only execution core for BTCUSDT spot trading.
//!
//! This crate deliberately has no network, venue, clock, daemon, or live-order
//! dependency. External events are authoritative and enter through [`event`].

pub mod engine;
pub mod event;
pub mod fee;
pub mod order;
pub mod portfolio;
pub mod risk;
pub mod slippage;
pub mod types;
