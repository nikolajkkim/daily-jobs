// Supabase connection for syncing with tracker.xlsx.
// The publishable (anon) key is safe to have here: the database only lets your signed-in email read or write.
// Leave both empty to run the site without sync (marks are then saved in this browser only).
window.DAILY_JOBS_CONFIG = {
  supabaseUrl: "https://xsrmswbbakfqfvpdxtjo.supabase.co",
  supabaseKey: "sb_publishable_jsqmDm4_wYTTXIM23qHvLA_24VHXfCH"
};
