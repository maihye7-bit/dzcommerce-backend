"""
Phase 9 Tests: Lost Sales Recovery & COD Intelligence.
"""
import uuid
import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.customer import Customer
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.order import Order, OrderItem, OrderStatus
from app.models.sales_opportunity import SalesOpportunity, OpportunityType, OpportunityStatus
from app.models.cod_risk import CODRiskScore
from app.services import lost_sales_service, cod_intelligence_service, order_service


def _make_store_customer(db):
    store_id = uuid.uuid4()
    customer = Customer(store_id=store_id, name="Test Customer")
    db.add(customer)
    db.flush()
    return store_id, customer.id


def _make_product(db, store_id, price=Decimal("100.00"), qty=10):
    product = Product(store_id=store_id, name="Test Product", price=price)
    db.add(product)
    db.flush()
    inv = Inventory(store_id=store_id, product_id=product.id, quantity=qty)
    db.add(inv)
    db.flush()
    return product.id


# ============================================================
# LOST SALES TESTS
# ============================================================

class TestLostSalesService:
    def test_create_opportunity(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        opp = lost_sales_service.create_opportunity(
            db=db_session,
            store_id=store_id,
            customer_id=customer_id,
            opp_type=OpportunityType.PRICE_INQUIRY,
            notes="Customer asked about price but didn't buy.",
        )
        assert opp.status == OpportunityStatus.OPEN
        assert opp.opportunity_type == OpportunityType.PRICE_INQUIRY

    def test_get_open_opportunities(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        lost_sales_service.create_opportunity(db_session, store_id, customer_id, OpportunityType.GENERAL_INTEREST)
        lost_sales_service.create_opportunity(db_session, store_id, customer_id, OpportunityType.ABANDONED_DRAFT)
        
        opps = lost_sales_service.get_open_opportunities(db_session, store_id)
        assert len(opps) == 2

    def test_mark_as_followed_up(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        opp = lost_sales_service.create_opportunity(db_session, store_id, customer_id, OpportunityType.GENERAL_INTEREST)
        
        updated = lost_sales_service.mark_as_followed_up(db_session, opp.id)
        assert updated.status == OpportunityStatus.FOLLOWED_UP
        assert updated.last_contacted_at is not None

    def test_check_abandoned_drafts_creates_opportunity(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id)
        
        # Create a draft that looks "old" by manipulating created_at
        order = order_service.create_draft(db_session, store_id, customer_id)
        order.created_at = datetime.utcnow() - timedelta(hours=25)
        db_session.commit()
        
        opps = lost_sales_service.check_abandoned_drafts(db_session, store_id, hours_threshold=24)
        assert len(opps) == 1
        assert opps[0].related_order_id == order.id


# ============================================================
# COD INTELLIGENCE TESTS
# ============================================================

class TestCODIntelligence:
    def test_new_customer_neutral_risk(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        score = cod_intelligence_service.calculate_risk_score(db_session, store_id, customer_id)
        assert score.risk_score == 50  # Neutral for new customers

    def test_trusted_customer_low_risk(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=100)
        
        # Simulate 5 successful completed orders
        for _ in range(5):
            order = order_service.create_draft(db_session, store_id, customer_id)
            order_service.add_item(db_session, store_id, order.id, product_id, 1)
            order_service.confirm_order(db_session, store_id, order.id)
            # Manually set to COMPLETED for this test logic
            order.status = OrderStatus.COMPLETED
            db_session.commit()

        score = cod_intelligence_service.calculate_risk_score(db_session, store_id, customer_id)
        assert score.total_orders == 5
        assert score.rejected_orders == 0
        assert score.risk_score == 0  # Low risk

    def test_risky_customer_high_risk(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=100)
        
        # Simulate 2 completed and 2 cancelled (rejected) orders
        for i in range(4):
            order = order_service.create_draft(db_session, store_id, customer_id)
            order_service.add_item(db_session, store_id, order.id, product_id, 1)
            order_service.confirm_order(db_session, store_id, order.id)
            if i < 2:
                order.status = OrderStatus.COMPLETED
            else:
                order.status = OrderStatus.CANCELLED
            db_session.commit()

        score = cod_intelligence_service.calculate_risk_score(db_session, store_id, customer_id)
        assert score.total_orders == 4
        assert score.rejected_orders == 2
        assert score.risk_score == 50  # 50% rejection rate


# ============================================================
# AGENT TOOLS TESTS
# ============================================================

class TestCODRiskTool:
    @pytest.mark.asyncio
    async def test_check_cod_risk_tool(self, db_session):
        from app.agent.tools.check_cod_risk import CheckCODRiskTool
        store_id, customer_id = _make_store_customer(db_session)
        
        tool = CheckCODRiskTool()
        result = await tool.execute(
            store_id=store_id,
            arguments={"customer_id": str(customer_id)},
            context={"db": db_session}
        )
        
        assert result.success is True
        assert "risk_score" in result.data
