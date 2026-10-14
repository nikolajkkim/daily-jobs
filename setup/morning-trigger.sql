-- Daily Jobs: start the morning scan from Supabase (reliable timer).
-- Run once in Supabase → SQL Editor. Replace PASTE_GITHUB_TOKEN_HERE first.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- 1) Store the GitHub token in Supabase Vault (encrypted).
--    To replace it later: select vault.update_secret((select id from vault.secrets where name = 'github_dispatch_token'), 'NEW_TOKEN');
select vault.create_secret('PASTE_GITHUB_TOKEN_HERE', 'github_dispatch_token', 'Starts the Daily Jobs morning scan');

-- 2) Function that asks GitHub to run the "Morning scan" workflow.
create or replace function public.dispatch_morning_scan()
returns bigint
language plpgsql
security definer
set search_path = public, extensions
as $$
declare tok text; rid bigint;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  select net.http_post(
    url := 'https://api.github.com/repos/nikolajkkim/daily-jobs/actions/workflows/scan.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || tok,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'daily-jobs'),
    body := '{"ref":"main"}'::jsonb
  ) into rid;
  return rid;
end $$;
revoke execute on function public.dispatch_morning_scan() from public, anon, authenticated;

-- 3) "Run today's scan" button on the site (only works for your signed-in account).
create or replace function public.run_morning_scan()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_owner() then raise exception 'not allowed'; end if;
  perform public.dispatch_morning_scan();
end $$;
revoke execute on function public.run_morning_scan() from public, anon;
grant execute on function public.run_morning_scan() to authenticated;

-- 4) Timer: 10:20 and 11:20 UTC = 6:20 / 7:20 AM New York in summer (5:20 / 6:20 in winter).
--    The second run sees the first one finished and stops right away.
select cron.schedule('daily-jobs-morning', '20 10,11 * * *', $$select public.dispatch_morning_scan()$$);

-- Check: should list the job.
select jobname, schedule, active from cron.job where jobname = 'daily-jobs-morning';
