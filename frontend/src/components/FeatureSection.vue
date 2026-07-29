<template>
  <section id="features" class="py-16 sm:py-20 bg-bg-section" aria-labelledby="features-heading">
    <div class="max-w-6xl mx-auto px-4 sm:px-6">
      <div class="text-center mb-12">
        <h2 id="features-heading" class="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
          {{ t('features.title') }}
        </h2>
        <p class="text-text-secondary text-base max-w-xl mx-auto">
          {{ t('features.desc') }}
        </p>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-5">
        <article
          v-for="feature in features"
          :key="feature.title"
          class="group bg-white rounded-2xl p-6 border border-border-light shadow-sm hover:shadow-md hover:border-primary/20 transition-all"
        >
          <div class="w-12 h-12 rounded-xl flex items-center justify-center mb-4 text-2xl"
            :class="feature.bgClass" role="img" :aria-label="feature.title">
            {{ feature.icon }}
          </div>
          <h3 class="text-base font-semibold text-text-primary mb-2">{{ feature.title }}</h3>
          <p class="text-sm text-text-secondary leading-relaxed">{{ feature.desc }}</p>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n.js'

const { t } = useI18n()

const featureStyles = [
  {
    icon: '🌐',
    bgClass: 'bg-blue-50',
  },
  {
    icon: '⚡',
    bgClass: 'bg-amber-50',
  },
  {
    icon: '📱',
    bgClass: 'bg-green-50',
  },
  {
    icon: '🎬',
    bgClass: 'bg-purple-50',
  },
  {
    icon: '🤖',
    bgClass: 'bg-rose-50',
  },
]

const features = computed(() => t('features.items').map(([title, desc], index) => ({
  ...featureStyles[index],
  title,
  desc,
})))
</script>
