create table if not exists public.datasets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    storage_path text not null unique,
    row_count bigint not null default 0 check (row_count >= 0),
    created_at timestamptz not null default now()
);

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    dataset_id uuid not null references public.datasets(id) on delete cascade,
    title text not null default 'New conversation',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    tool_used text,
    created_at timestamptz not null default now()
);

create index if not exists datasets_user_created_idx
    on public.datasets (user_id, created_at desc);
create index if not exists conversations_user_updated_idx
    on public.conversations (user_id, updated_at desc);
create index if not exists messages_conversation_created_idx
    on public.messages (conversation_id, created_at);

alter table public.datasets enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

revoke all on public.datasets, public.conversations, public.messages from anon;
grant select, insert, update, delete on public.datasets to authenticated;
grant select, insert, update, delete on public.conversations to authenticated;
grant select, insert, delete on public.messages to authenticated;

drop policy if exists datasets_owner_access on public.datasets;
create policy datasets_owner_access
    on public.datasets for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists conversations_owner_access on public.conversations;
create policy conversations_owner_access
    on public.conversations for all to authenticated
    using (user_id = (select auth.uid()))
    with check (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.datasets d
            where d.id = dataset_id
              and d.user_id = (select auth.uid())
        )
    );

drop policy if exists messages_owner_access on public.messages;
create policy messages_owner_access
    on public.messages for all to authenticated
    using (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.conversations c
            where c.id = conversation_id
              and c.user_id = (select auth.uid())
        )
    )
    with check (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.conversations c
            where c.id = conversation_id
              and c.user_id = (select auth.uid())
        )
    );

insert into storage.buckets (id, name, public)
values ('datasets', 'datasets', false)
on conflict (id) do update set public = false;

revoke all on storage.objects from anon;
drop policy if exists dataset_files_owner_access on storage.objects;
create policy dataset_files_owner_access
    on storage.objects for all to authenticated
    using (
        bucket_id = 'datasets'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    )
    with check (
        bucket_id = 'datasets'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
