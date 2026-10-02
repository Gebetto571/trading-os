use base64::{engine::general_purpose::STANDARD, Engine as _};
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;
use trading_os_strategy_runtime::verify_and_replay_three_ledgers;

const GOLDEN_VECTOR: &str = include_str!("../../../schemas/strategy-contract-v1.golden.json");
const WARMUP_SAMPLES: usize = 32;
const MEASURED_SAMPLES: usize = 128;

struct CountingAllocator;

static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) }
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.realloc(pointer, layout, size) }
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

fn golden_wire() -> Vec<u8> {
    let wrapper: serde_json::Value = serde_json::from_str(GOLDEN_VECTOR).expect("golden wrapper");
    STANDARD
        .decode(
            wrapper["wire_utf8_base64"]
                .as_str()
                .expect("golden base64 string"),
        )
        .expect("golden bytes")
}

fn percentile(sorted: &[u128], percentile: usize) -> u128 {
    let index = (sorted.len() - 1) * percentile / 100;
    sorted[index]
}

#[test]
fn three_ledger_replay_reports_integer_latency_throughput_and_allocations() {
    let raw = golden_wire();
    for _ in 0..WARMUP_SAMPLES {
        verify_and_replay_three_ledgers(&raw).expect("warmup B0 replay");
    }

    let mut samples_ns = Vec::with_capacity(MEASURED_SAMPLES);
    let mut event_count = 0_usize;
    ALLOCATIONS.store(0, Ordering::SeqCst);
    for _ in 0..MEASURED_SAMPLES {
        let started = Instant::now();
        let outcome = verify_and_replay_three_ledgers(&raw).expect("measured B0 replay");
        samples_ns.push(started.elapsed().as_nanos());
        event_count = outcome.idealized.applied_event_count;
    }
    let allocation_count = ALLOCATIONS.load(Ordering::SeqCst);
    samples_ns.sort_unstable();
    let p50_ns = percentile(&samples_ns, 50);
    let p95_ns = percentile(&samples_ns, 95);
    let p99_ns = percentile(&samples_ns, 99);
    let throughput_events_per_second = (event_count as u128)
        .checked_mul(1_000_000_000_u128)
        .and_then(|numerator| numerator.checked_div(p50_ns.max(1)))
        .expect("throughput must fit");
    let allocations_per_event_ppm = (allocation_count as u128)
        .checked_mul(1_000_000_u128)
        .and_then(|numerator| numerator.checked_div((event_count * MEASURED_SAMPLES) as u128))
        .expect("allocation metric must fit");

    assert!(p50_ns > 0);
    assert!(p50_ns <= p95_ns && p95_ns <= p99_ns);
    assert!(throughput_events_per_second > 0);
    assert!(event_count > 0);
    println!(
        "B0 replay metrics: p50_ns={p50_ns}; p95_ns={p95_ns}; p99_ns={p99_ns}; \
         throughput_events_per_second={throughput_events_per_second}; allocations={allocation_count}; \
         event_count={event_count}; allocations_per_event_ppm={allocations_per_event_ppm}"
    );
}
