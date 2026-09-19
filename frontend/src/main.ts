import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./app/router";
import "./styles/main.css";
import "./styles/motion.css";

createApp(App).use(router).mount("#app");
