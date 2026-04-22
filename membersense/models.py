from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .db import Base


JSONType = JSON


class Member(Base):
    __tablename__ = "membersense_members"

    id = Column(Integer, primary_key=True)
    external_member_id = Column(String(64), nullable=True, unique=True, index=True)
    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    phone_e164 = Column(String(32), nullable=False, unique=True, index=True)
    mobile_raw = Column(String(64), nullable=True, index=True)
    email = Column(String(255), nullable=True)
    membership_status = Column(String(32), nullable=False, default="current", index=True)
    join_date = Column(Date, nullable=True)
    last_visit_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    cancellation_date = Column(Date, nullable=True)
    source = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    conversations = relationship("Conversation", back_populates="member")
    tasks = relationship("StaffTask", back_populates="member")


class Conversation(Base):
    __tablename__ = "membersense_conversations"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("membersense_members.id", ondelete="CASCADE"), nullable=False, index=True)
    flow_key = Column(String(64), nullable=False, index=True)
    app_link_token = Column(String(96), nullable=True, unique=True, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    step_index = Column(Integer, nullable=False, default=0)
    answers = Column(JSONType, nullable=False, default=dict)
    classification = Column(JSONType, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    member = relationship("Member", back_populates="conversations")
    messages = relationship("MessageLog", back_populates="conversation")
    tasks = relationship("StaffTask", back_populates="conversation")


class MessageLog(Base):
    __tablename__ = "membersense_message_logs"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("membersense_members.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("membersense_conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    direction = Column(String(16), nullable=False)
    channel = Column(String(32), nullable=False, default="sms")
    phone_e164 = Column(String(32), nullable=True, index=True)
    body = Column(Text, nullable=True)
    provider_sid = Column(String(128), nullable=True, index=True)
    status = Column(String(32), nullable=True)
    raw_payload = Column(JSONType, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


class SurveyConfig(Base):
    __tablename__ = "membersense_survey_configs"

    id = Column(Integer, primary_key=True)
    flow_key = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(180), nullable=True)
    intro = Column(Text, nullable=True)
    completion = Column(Text, nullable=True)
    questions = Column(JSONType, nullable=True)
    avatar_script = Column(Text, nullable=True)
    avatar_video_url = Column(Text, nullable=True)
    avatar_poster_url = Column(Text, nullable=True)
    avatar_character = Column(String(80), nullable=True)
    avatar_style = Column(String(120), nullable=True)
    avatar_voice = Column(String(160), nullable=True)
    avatar_status = Column(String(32), nullable=True)
    avatar_job_id = Column(String(128), nullable=True)
    avatar_error = Column(Text, nullable=True)
    avatar_summary_url = Column(Text, nullable=True)
    avatar_source = Column(String(64), nullable=True)
    avatar_payload = Column(JSONType, nullable=True)
    avatar_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class StaffTask(Base):
    __tablename__ = "membersense_staff_tasks"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("membersense_members.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("membersense_conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    task_type = Column(String(64), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    detail = Column(Text, nullable=True)
    priority = Column(String(32), nullable=False, default="normal", index=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    member = relationship("Member", back_populates="tasks")
    conversation = relationship("Conversation", back_populates="tasks")


class StaffUser(Base):
    __tablename__ = "membersense_staff_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=True, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False)
    mobile = Column(String(64), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="staff", index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class OkrObjective(Base):
    __tablename__ = "membersense_okr_objectives"

    id = Column(Integer, primary_key=True)
    quarter = Column(String(16), nullable=False, index=True)
    objective_number = Column(Integer, nullable=True, index=True)
    area = Column(String(160), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    description = Column(Text, nullable=True)
    champions = Column(String(240), nullable=True)
    owner_staff_id = Column(Integer, ForeignKey("membersense_staff_users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("StaffUser", foreign_keys=[owner_staff_id])
    key_results = relationship("OkrKeyResult", back_populates="objective", cascade="all, delete-orphan")


class OkrKeyResult(Base):
    __tablename__ = "membersense_okr_key_results"

    id = Column(Integer, primary_key=True)
    objective_id = Column(Integer, ForeignKey("membersense_okr_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    key_result_number = Column(Integer, nullable=True, index=True)
    title = Column(String(240), nullable=False)
    target_value = Column(Float, nullable=False, default=0.0)
    actual_value = Column(Float, nullable=False, default=0.0)
    actual_updated_at = Column(DateTime, nullable=True)
    unit = Column(String(40), nullable=True)
    direction = Column(String(24), nullable=False, default="increase")
    allocation_type = Column(String(24), nullable=False, default="team", index=True)
    assigned_staff_id = Column(Integer, ForeignKey("membersense_staff_users.id", ondelete="SET NULL"), nullable=True, index=True)
    team_label = Column(String(160), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    objective = relationship("OkrObjective", back_populates="key_results")
    assigned_staff = relationship("StaffUser", foreign_keys=[assigned_staff_id])


class ImportBatch(Base):
    __tablename__ = "membersense_import_batches"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=True)
    source = Column(String(64), nullable=True)
    rows_seen = Column(Integer, nullable=False, default=0)
    rows_created = Column(Integer, nullable=False, default=0)
    rows_updated = Column(Integer, nullable=False, default=0)
    rows_skipped = Column(Integer, nullable=False, default=0)
    errors = Column(JSONType, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "membersense_app_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(120), nullable=False)
    value = Column(Text, nullable=True)
    is_secret = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("key", name="uq_membersense_app_settings_key"),)
