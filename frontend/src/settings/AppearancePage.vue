<script setup lang="ts">
import { themeDefinitions } from "../appearance/appearanceState";
import { useAppearance } from "../appearance/useAppearance";
const { preferences, selectTheme } = useAppearance();
</script>

<template>
  <section class="page-stack" aria-labelledby="appearance-title">
    <header class="page-heading">
      <p class="eyebrow">让这里，更像你</p>
      <h1 id="appearance-title">外观</h1>
      <p class="muted">选一种陪伴今天的颜色。偏好只保存在当前浏览器。</p>
    </header>
    <div class="theme-grid">
      <button
        v-for="item in themeDefinitions"
        :key="item.id"
        class="theme-choice"
        :data-palette="item.id"
        :aria-pressed="preferences.theme === item.id"
        @click="selectTheme(item.id)"
      >
        <span class="theme-preview"
          ><img v-if="item.assets" :src="item.assets.emblem" alt="" /><span
            v-else
            >◯</span
          ></span
        >
        <span>{{ item.label }}</span
        ><span v-if="preferences.theme === item.id" class="badge">已选择</span>
      </button>
    </div>
    <div v-if="preferences.theme === 'minimal'" class="panel form-grid">
      <label class="field"
        >主题色相 <output>{{ preferences.minimal.accentHue }}°</output
        ><input
          v-model.number="preferences.minimal.accentHue"
          type="range"
          min="0"
          max="359"
      /></label>
      <label class="field"
        >背景明度 <output>{{ preferences.minimal.backgroundLightness }}%</output
        ><input
          v-model.number="preferences.minimal.backgroundLightness"
          type="range"
          min="88"
          max="100"
      /></label>
    </div>
    <p class="muted">装饰随主题变化，简约主题只保留色彩与留白。</p>
  </section>
</template>
