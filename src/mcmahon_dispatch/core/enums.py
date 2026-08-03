from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class CustomerStatus(StrEnum):
    LEAD = "lead"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DO_NOT_SERVE = "do_not_serve"
    ARCHIVED = "archived"


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_INFORMATION = "needs_information"
    RESEARCH_REQUIRED = "research_required"
    READY_TO_SEND = "ready_to_send"
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CONVERTED = "converted"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class JobStatus(StrEnum):
    DRAFT = "draft"
    QUOTED = "quoted"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    PICKING_UP = "picking_up"
    WAITING = "waiting"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"
    FAILED_PICKUP = "failed_pickup"
    FAILED_DELIVERY = "failed_delivery"
    RETURN = "return"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    SENT = "sent"
    VIEWED = "viewed"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"
    WRITTEN_OFF = "written_off"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    VOIDED = "voided"


class VehicleStatus(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    RESERVED = "reserved"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    INACTIVE = "inactive"


class DriverStatus(StrEnum):
    AVAILABLE = "available"
    ON_DUTY = "on_duty"
    ASSIGNED = "assigned"
    ON_JOB = "on_job"
    OFF_DUTY = "off_duty"
    TIME_OFF = "time_off"
    UNAVAILABLE = "unavailable"
    INACTIVE = "inactive"


class StopType(StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"
    RETURN = "return"
    OTHER = "other"


class DocumentStatus(StrEnum):
    ACTIVE = "active"
    PROCESSING = "processing"
    QUARANTINED = "quarantined"
    DELETED = "deleted"
