import os
import uuid
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import get_current_user
from database import (
    create_order,
    update_order_stripe_session,
    complete_order,
    get_user_orders,
    get_user_by_id,
    get_order_by_no,
)

router = APIRouter(prefix="/api/payment", tags=["payment"])


def _get_config(key: str, default: str = "") -> str:
    """每次调用时实时读取环境变量，确保 load_dotenv 后的值能被读到"""
    return os.getenv(key, default)


PLANS = {
    "monthly": {
        "name": "镜读 VIP 月度会员",
        "amount": 990,
        "currency": "cny",
    },
}


class CreateCheckoutRequest(BaseModel):
    plan_type: str = "monthly"


class ConfirmPaymentRequest(BaseModel):
    order_no: str


def _generate_order_no(user_id: int) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"SA{ts}{user_id:04d}{short_uuid}"


def _stripe_get(obj, key: str, default=None):
    """兼容 StripeObject 和普通 dict 的字段读取。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return getattr(obj, key)
    except AttributeError:
        try:
            return obj[key]
        except Exception:
            return default


def _complete_paid_session(session) -> dict | None:
    payment_status = _stripe_get(session, "payment_status")
    if payment_status != "paid":
        return None

    session_id = _stripe_get(session, "id")
    payment_intent_id = _stripe_get(session, "payment_intent", "") or ""
    if not session_id:
        return None
    return complete_order(session_id, payment_intent_id)


def _safe_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "is_vip": bool(user["is_vip"]),
        "vip_expire_at": user["vip_expire_at"],
    }


@router.post("/create-checkout")
async def create_checkout_session(req: CreateCheckoutRequest, user: dict = Depends(get_current_user)):
    secret_key = _get_config("STRIPE_SECRET_KEY")
    price_id = _get_config("STRIPE_PRICE_ID_MONTHLY")
    frontend_url = _get_config("FRONTEND_URL", "http://localhost:5173")

    if not secret_key:
        raise HTTPException(status_code=500, detail="支付服务未配置，请设置 STRIPE_SECRET_KEY")
    if not price_id:
        raise HTTPException(status_code=500, detail="套餐价格未配置，请设置 STRIPE_PRICE_ID_MONTHLY")

    plan = PLANS.get(req.plan_type)
    if not plan:
        raise HTTPException(status_code=400, detail="无效的套餐类型")

    stripe.api_key = secret_key

    order_no = _generate_order_no(user["id"])
    create_order(
        user_id=user["id"],
        order_no=order_no,
        amount=plan["amount"],
        currency=plan["currency"],
        plan_type=req.plan_type,
    )

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=f"{frontend_url}?payment=success&order_no={order_no}",
            cancel_url=f"{frontend_url}?payment=cancel&order_no={order_no}",
            client_reference_id=str(user["id"]),
            customer_email=user["email"],
            metadata={
                "order_no": order_no,
                "user_id": str(user["id"]),
                "plan_type": req.plan_type,
            },
        )

        update_order_stripe_session(order_no, session.id)

        return {
            "success": True,
            "data": {
                "checkout_url": session.url,
                "order_no": order_no,
                "session_id": session.id,
            },
        }

    except stripe.StripeError as e:
        raise HTTPException(status_code=400, detail=f"创建支付会话失败: {str(e)}")


@router.post("/confirm")
async def confirm_payment(req: ConfirmPaymentRequest, user: dict = Depends(get_current_user)):
    """
    支付成功页回跳后的兜底确认。
    Webhook 仍是主链路；该接口用于处理本地开发中 Stripe CLI 未连上、
    webhook 延迟或 webhook 失败导致用户状态没有及时刷新的情况。
    """
    secret_key = _get_config("STRIPE_SECRET_KEY")
    if not secret_key:
        raise HTTPException(status_code=500, detail="支付服务未配置，请设置 STRIPE_SECRET_KEY")

    order = get_order_by_no(req.order_no)
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order["status"] == "paid":
        refreshed_user = get_user_by_id(user["id"])
        return {"success": True, "data": {"paid": True, "user": _safe_user(refreshed_user)}}

    session_id = order.get("stripe_session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="订单尚未创建支付会话")

    stripe.api_key = secret_key
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError as e:
        raise HTTPException(status_code=400, detail=f"查询支付状态失败: {str(e)}")

    completed = _complete_paid_session(session)
    refreshed_user = get_user_by_id(user["id"])
    return {
        "success": True,
        "data": {
            "paid": bool(completed or order["status"] == "paid"),
            "user": _safe_user(refreshed_user),
        },
    }


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe Webhook 回调处理。
    幂等性由 complete_order 保证：只有 pending 状态的订单才会被处理。
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    webhook_secret = _get_config("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        return JSONResponse(status_code=400, content={"error": "Webhook secret not configured"})

    stripe.api_key = _get_config("STRIPE_SECRET_KEY")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})
    except stripe.SignatureVerificationError:
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        result = _complete_paid_session(session)
        session_id = _stripe_get(session, "id", "")
        if result:
            print(f"[Payment] Order {result['order_no']} completed successfully")
        else:
            print(f"[Payment] Session {session_id} already processed, unpaid, or not found")

    elif event["type"] == "checkout.session.async_payment_succeeded":
        session = event["data"]["object"]
        _complete_paid_session(session)

    return JSONResponse(status_code=200, content={"received": True})


@router.get("/orders")
async def list_orders(user: dict = Depends(get_current_user)):
    orders = get_user_orders(user["id"])
    return {
        "success": True,
        "data": [
            {
                "order_no": o["order_no"],
                "amount": o["amount"],
                "currency": o["currency"],
                "status": o["status"],
                "plan_type": o["plan_type"],
                "created_at": o["created_at"],
                "paid_at": o["paid_at"],
            }
            for o in orders
        ],
    }
