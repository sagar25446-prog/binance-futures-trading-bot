from decimal import Decimal
import pytest

from bot.validators import ExchangeValidator
from bot.models import SymbolInfo, LotSizeFilter, PriceFilter, MinNotionalFilter
from bot.exceptions import ValidationError

@pytest.fixture
def dummy_symbol_info():
    return SymbolInfo(
        symbol="BTCUSDT",
        status="TRADING",
        baseAsset="BTC",
        quoteAsset="USDT",
        pricePrecision=2,
        quantityPrecision=3,
        lot_size=LotSizeFilter(minQty=Decimal("0.001"), maxQty=Decimal("1000"), stepSize=Decimal("0.001")),
        price_filter=PriceFilter(minPrice=Decimal("10"), maxPrice=Decimal("1000000"), tickSize=Decimal("0.1")),
        min_notional=MinNotionalFilter(notional=Decimal("5"))
    )

def test_validate_quantity_success(dummy_symbol_info):
    # Valid quantity
    ExchangeValidator._validate_quantity(Decimal("0.005"), dummy_symbol_info)

def test_validate_quantity_min_qty(dummy_symbol_info):
    with pytest.raises(ValidationError) as exc:
        ExchangeValidator._validate_quantity(Decimal("0.0005"), dummy_symbol_info)
    assert "below the minimum" in str(exc.value)

def test_validate_quantity_step_size(dummy_symbol_info):
    with pytest.raises(ValidationError) as exc:
        ExchangeValidator._validate_quantity(Decimal("0.0015"), dummy_symbol_info)
    assert "step size" in str(exc.value)

def test_validate_price_success(dummy_symbol_info):
    # Valid price
    ExchangeValidator._validate_price(Decimal("50000.5"), dummy_symbol_info)

def test_validate_price_tick_size(dummy_symbol_info):
    with pytest.raises(ValidationError) as exc:
        ExchangeValidator._validate_price(Decimal("50000.55"), dummy_symbol_info)
    assert "tick size" in str(exc.value)

def test_validate_price_min_price(dummy_symbol_info):
    with pytest.raises(ValidationError) as exc:
        ExchangeValidator._validate_price(Decimal("5.0"), dummy_symbol_info)
    assert "below the minimum" in str(exc.value)
