import { createRouter, createWebHistory } from "vue-router";
import RealtimeMonitor from "../views/RealtimeMonitor.vue";
import AudioAnalysis from "../views/AudioAnalysis.vue";

const routes = [
  { path: "/", redirect: "/realtime" },
  { path: "/realtime", component: RealtimeMonitor },
  { path: "/audio-analysis", component: AudioAnalysis },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
