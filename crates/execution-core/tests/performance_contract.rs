use std::time::{Duration, Instant};

use trading_os_execution_core::engine::{reduce, EngineState};
use trading_os_execution_core::event::{CoreMessage, EngineInput};
use trading_os_execution_core::order::{NewOrder, OrderCommand, OrderKind};
use trading_os_execution_core::types::{
    BtcAtoms, EngineSeq, Instrument, InstrumentSpec, IntentId, PriceTicks, QuantityLots, Side,
    SourceId, TimestampMicros, UsdtAtoms,
};

const SAMPLE_COUNT: usize = 128;
const P99_BUDGET: Duration = Duration::from_millis(1);

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

fn input() -> EngineInput {
    EngineInput {
        engine_seq: EngineSeq::new(1),
        source_id: SourceId::new(1).unwrap(),
        source_seq: None,
        source_event_time: TimestampMicros::new(1),
        message: CoreMessage::Command(OrderCommand::Submit(NewOrder {
            intent_id: IntentId::new(1).unwrap(),
            instrument: Instrument::BtcUsdt,
            side: Side::Buy,
            kind: OrderKind::Limit {
                price: PriceTicks::new(100).unwrap(),
            },
            quantity: QuantityLots::new(1).unwrap(),
        })),
    }
}

#[test]
fn reducer_submit_p99_stays_inside_the_declared_hot_path_budget() {
    let state = EngineState::new(spec());
    let candidate = input();

    for _ in 0..32 {
        reduce(&state, &candidate).unwrap();
    }

    let mut samples = Vec::with_capacity(SAMPLE_COUNT);
    for _ in 0..SAMPLE_COUNT {
        let started = Instant::now();
        reduce(&state, &candidate).unwrap();
        samples.push(started.elapsed());
    }
    samples.sort_unstable();
    let p99 = samples[(SAMPLE_COUNT * 99).div_ceil(100) - 1];
    assert!(
        p99 <= P99_BUDGET,
        "p99 reducer submit latency {p99:?} exceeded declared budget {P99_BUDGET:?}"
    );
}
