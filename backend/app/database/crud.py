from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Thread, Message


async def create_thread(db: AsyncSession, title: str, parent_id: UUID | None = None) -> Thread:
    thread = Thread(title=title, parent_id=parent_id)
    db.add(thread)
    await db.flush()
    await db.refresh(thread)
    return thread


async def get_thread(db: AsyncSession, thread_id: UUID) -> Thread | None:
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id)
    )
    return result.scalar_one_or_none()


async def get_thread_with_messages(db: AsyncSession, thread_id: UUID) -> Thread | None:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Thread)
        .where(Thread.id == thread_id)
        .options(selectinload(Thread.messages))
    )
    return result.scalar_one_or_none()


async def get_root_threads(db: AsyncSession, limit: int = 50, offset: int = 0) -> list[Thread]:
    result = await db.execute(
        select(Thread)
        .where(Thread.parent_id.is_(None))
        .order_by(Thread.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_child_threads(db: AsyncSession, parent_id: UUID) -> list[Thread]:
    result = await db.execute(
        select(Thread)
        .where(Thread.parent_id == parent_id)
        .order_by(Thread.created_at)
    )
    return list(result.scalars().all())


async def add_message(db: AsyncSession, thread_id: UUID, role: str, content: str, metadata: dict | None = None) -> Message:
    message = Message(thread_id=thread_id, role=role, content=content, metadata_=metadata)
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def get_thread_messages(db: AsyncSession, thread_id: UUID) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def update_thread_title(db: AsyncSession, thread_id: UUID, title: str) -> Thread | None:
    thread = await get_thread(db, thread_id)
    if thread:
        thread.title = title
        await db.flush()
        await db.refresh(thread)
    return thread


async def delete_thread(db: AsyncSession, thread_id: UUID) -> bool:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Thread)
        .options(selectinload(Thread.messages))
        .where(Thread.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if thread:
        await db.delete(thread)
        await db.flush()
        return True
    return False


async def get_message_count(db: AsyncSession, thread_id: UUID) -> int:
    result = await db.execute(
        select(func.count(Message.id)).where(Message.thread_id == thread_id)
    )
    return result.scalar_one()
