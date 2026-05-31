-- =====================================================================
-- Shared Supabase schema for SMS Forwarder + Account Automation Lab.
--
-- Run this once on the single Supabase project used by both apps.
-- Safe to re-run: tables/indexes use IF NOT EXISTS; existing SMS tables
-- are upgraded with ALTER TABLE ADD COLUMN IF NOT EXISTS.
-- =====================================================================

-- ---------------------------------------------------------------------
-- SMS Forwarder tables
-- ---------------------------------------------------------------------

create table if not exists public.contacts (
  phone       text primary key,
  name        text,
  note        text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.login_accounts (
  id                    uuid primary key default gen_random_uuid(),
  account_name          text not null,
  phone                 text not null,
  password              text not null,
  enabled               boolean not null default true,
  login_url             text,
  phone_selector        text,
  password_selector     text,
  submit_selector       text,
  otp_selector          text,
  keepalive_selector_a  text,
  keepalive_selector_b  text,
  note                  text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists login_accounts_enabled_name_idx
  on public.login_accounts (enabled, account_name);
create index if not exists login_accounts_phone_idx
  on public.login_accounts (phone);

create table if not exists public.regex_overrides (
  id              uuid primary key default gen_random_uuid(),
  sender_match    text not null,
  regex_pattern   text not null,
  description     text,
  enabled         boolean not null default true,
  priority        int not null default 100,
  created_at      timestamptz not null default now()
);

create index if not exists regex_overrides_enabled_idx
  on public.regex_overrides (enabled, priority);

create table if not exists public.otp_messages (
  id                         uuid primary key default gen_random_uuid(),
  sender_phone               text not null,
  sender_phone_normalized    text,
  receiver_phone             text,
  receiver_phone_normalized  text,
  sender_name                text,
  raw_message                text not null,
  otp                        text not null,
  sms_sent_at                timestamptz,
  received_at                timestamptz not null default now(),
  telegram_sent              boolean not null default false,
  telegram_error             text
);

alter table public.otp_messages
  add column if not exists sender_phone_normalized text,
  add column if not exists receiver_phone text,
  add column if not exists receiver_phone_normalized text;

create index if not exists otp_messages_received_at_idx
  on public.otp_messages (received_at desc);
create index if not exists otp_messages_sender_idx
  on public.otp_messages (sender_phone);
create index if not exists otp_messages_receiver_norm_received_idx
  on public.otp_messages (receiver_phone_normalized, received_at desc);

create table if not exists public.cache_meta (
  id          int primary key check (id = 1),
  version     int not null default 1,
  updated_at  timestamptz not null default now()
);

insert into public.cache_meta (id, version) values (1, 1)
  on conflict (id) do nothing;

-- ---------------------------------------------------------------------
-- Account Automation Lab tables
-- ---------------------------------------------------------------------

create table if not exists public.automation_sites (
  key text primary key,
  display_name text not null,
  base_url text not null,
  enabled boolean not null default true,
  captcha_mode text not null default 'test_key',
  proxy_policy text not null default 'sticky_profile',
  otp_sender_hints text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.automation_sites
  add column if not exists description text not null default '';

insert into public.automation_sites (key, display_name, base_url, description)
  values (
    'example',
    'Example Site',
    'http://localhost:8080/mock/example',
    'Worked example adapter. Clone its module to add a real site.'
  )
  on conflict (key) do nothing;

create table if not exists public.automation_sims (
  id text primary key,
  label text not null,
  phone text,
  phone_normalized text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists automation_sims_phone_normalized_idx
  on public.automation_sims (phone_normalized);

create table if not exists public.automation_profile_groups (
  id text primary key,
  name text not null,
  color text,
  created_at timestamptz not null default now()
);

create table if not exists public.automation_profiles (
  id text primary key,
  sim_id text not null references public.automation_sims(id),
  site_key text not null references public.automation_sites(key),
  storage_dir text not null,
  proxy_id uuid,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (sim_id, site_key)
);

create index if not exists automation_profiles_sim_id_idx
  on public.automation_profiles (sim_id);
create index if not exists automation_profiles_site_key_idx
  on public.automation_profiles (site_key);

alter table public.automation_profiles
  add column if not exists name text,
  add column if not exists group_id text references public.automation_profile_groups(id),
  add column if not exists tags text[] not null default '{}',
  add column if not exists notes text not null default '',
  add column if not exists runtime text not null default 'cloakbrowser',
  add column if not exists startup_url text,
  add column if not exists status text not null default 'active',
  add column if not exists fingerprint jsonb not null default '{}';

alter table public.automation_profiles alter column sim_id drop not null;
alter table public.automation_profiles alter column site_key drop not null;

create table if not exists public.automation_proxies (
  id uuid primary key default gen_random_uuid(),
  profile_id text references public.automation_profiles(id),
  proxy_url text not null,
  policy text not null,
  status text not null default 'active',
  issued_at timestamptz not null default now(),
  expires_at timestamptz
);

create index if not exists automation_proxies_profile_id_idx
  on public.automation_proxies (profile_id);
create index if not exists automation_proxies_status_expires_at_idx
  on public.automation_proxies (status, expires_at);

create table if not exists public.automation_jobs (
  id uuid primary key default gen_random_uuid(),
  site_key text not null references public.automation_sites(key),
  sim_id text not null references public.automation_sims(id),
  profile_id text references public.automation_profiles(id),
  runtime text not null default 'playwright_chromium',
  status text not null default 'queued',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists automation_jobs_status_created_at_idx
  on public.automation_jobs (status, created_at);
create index if not exists automation_jobs_site_status_idx
  on public.automation_jobs (site_key, status);
create index if not exists automation_jobs_sim_id_idx
  on public.automation_jobs (sim_id);
create index if not exists automation_jobs_profile_id_idx
  on public.automation_jobs (profile_id);

create table if not exists public.automation_job_events (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.automation_jobs(id) on delete cascade,
  event_type text not null,
  message text not null,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists automation_job_events_job_created_at_idx
  on public.automation_job_events (job_id, created_at);

create table if not exists public.automation_accounts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references public.automation_jobs(id),
  site_key text not null references public.automation_sites(key),
  sim_id text not null references public.automation_sims(id),
  account_identifier text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (site_key, account_identifier)
);

create index if not exists automation_accounts_job_id_idx
  on public.automation_accounts (job_id);
create index if not exists automation_accounts_sim_id_idx
  on public.automation_accounts (sim_id);

create table if not exists public.automation_job_artifacts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.automation_jobs(id) on delete cascade,
  artifact_type text not null,
  path text not null,
  created_at timestamptz not null default now()
);

create index if not exists automation_job_artifacts_job_id_idx
  on public.automation_job_artifacts (job_id);

create table if not exists public.automation_captcha_tasks (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.automation_jobs(id) on delete cascade,
  mode text not null,
  status text not null default 'waiting',
  provider_ref text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists automation_captcha_tasks_job_id_idx
  on public.automation_captcha_tasks (job_id);
create index if not exists automation_captcha_tasks_status_created_at_idx
  on public.automation_captcha_tasks (status, created_at);

-- ---------------------------------------------------------------------
-- Service-role only MVP. Do not expose service_role in browsers/extensions.
-- ---------------------------------------------------------------------

alter table public.contacts                    disable row level security;
alter table public.login_accounts              disable row level security;
alter table public.regex_overrides             disable row level security;
alter table public.otp_messages                disable row level security;
alter table public.cache_meta                  disable row level security;
alter table public.automation_sites            disable row level security;
alter table public.automation_sims             disable row level security;
alter table public.automation_profile_groups   disable row level security;
alter table public.automation_profiles         disable row level security;
alter table public.automation_proxies          disable row level security;
alter table public.automation_jobs             disable row level security;
alter table public.automation_job_events       disable row level security;
alter table public.automation_accounts         disable row level security;
alter table public.automation_job_artifacts    disable row level security;
alter table public.automation_captcha_tasks    disable row level security;

notify pgrst, 'reload schema';
