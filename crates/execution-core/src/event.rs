//! Ordered input events. The core never obtains market or fill data itself.

use crate::order::OrderCommand;
use crate::types::{
    EngineSeq, FillId, Instrument, OrderId, PriceTicks, QuantityLots, Side, SourceId, SourceSeq,
    TimestampMicros,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MarketTrade {
    pub instrument: Instrument,
    pub price: PriceTicks,
    pub quantity: QuantityLots,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExternalFill {
    pub fill_id: FillId,
    pub order_id: OrderId,
    pub instrument: Instrument,
    pub side: Side,
    pub price: PriceTicks,
    pub quantity: QuantityLots,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExternalEvent {
    MarketTrade(MarketTrade),
    Fill(ExternalFill),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreMessage {
    Command(OrderCommand),
    External(ExternalEvent),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EngineInput {
    /// Canonical reducer sequence assigned by replay normalization.
    pub engine_seq: EngineSeq,
    /// Dataset or provider identity; it is provenance, not reducer ordering.
    pub source_id: SourceId,
    /// Optional provider sequence. It never replaces `engine_seq`.
    pub source_seq: Option<SourceSeq>,
    /// Timestamp supplied by the event source. The core never reads a clock.
    pub source_event_time: TimestampMicros,
    pub message: CoreMessage,
}

/// Source provenance retained by the reducer for the most recently accepted
/// event. These values never determine reducer ordering.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventProvenance {
    pub engine_seq: EngineSeq,
    pub source_id: SourceId,
    pub source_seq: Option<SourceSeq>,
    pub source_event_time: TimestampMicros,
}

impl EngineInput {
    pub const fn provenance(&self) -> EventProvenance {
        EventProvenance {
            engine_seq: self.engine_seq,
            source_id: self.source_id,
            source_seq: self.source_seq,
            source_event_time: self.source_event_time,
        }
    }
}
