use trading_os_execution_core::event::ExternalFill;
use trading_os_execution_core::fee::{FeePolicy, FeeUnits, ZeroFee};
use trading_os_execution_core::slippage::{SlippagePolicy, SlippageTicks, ZeroSlippage};
use trading_os_execution_core::types::{
    FillId, Instrument, OrderId, PriceTicks, QuantityLots, Side,
};

fn fill() -> ExternalFill {
    ExternalFill {
        fill_id: FillId::new(1).expect("positive fill id"),
        order_id: OrderId::new(1).expect("positive order id"),
        instrument: Instrument::BtcUsdt,
        side: Side::Buy,
        price: PriceTicks::new(1_000).expect("positive price"),
        quantity: QuantityLots::new(5).expect("positive quantity"),
    }
}

#[test]
fn default_fee_policy_is_zero() {
    assert_eq!(ZeroFee.fee_for(&fill()).get(), 0);
}

#[test]
fn custom_fee_policy_can_return_non_zero_units() {
    struct FixedFee;

    impl FeePolicy for FixedFee {
        fn fee_for(&self, _fill: &ExternalFill) -> FeeUnits {
            FeeUnits::new(7)
        }
    }

    assert_eq!(FixedFee.fee_for(&fill()).get(), 7);
}

#[test]
fn default_slippage_policy_reports_zero_without_changing_the_fill() {
    let authoritative_fill = fill();
    assert_eq!(
        ZeroSlippage
            .measure(&authoritative_fill, authoritative_fill.price)
            .get(),
        0
    );
    assert_eq!(authoritative_fill, fill());
}

#[test]
fn custom_slippage_policy_is_replaceable() {
    struct FixedSlippage;

    impl SlippagePolicy for FixedSlippage {
        fn measure(&self, _fill: &ExternalFill, _reference_price: PriceTicks) -> SlippageTicks {
            SlippageTicks::new(3)
        }
    }

    assert_eq!(FixedSlippage.measure(&fill(), fill().price).get(), 3);
}
