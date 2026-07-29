<template>
  <section id="how-to-use" class="py-16 sm:py-20 bg-white" aria-labelledby="howto-heading">
    <div class="max-w-5xl mx-auto px-4 sm:px-6">
      <div class="text-center mb-12">
        <h2 id="howto-heading" class="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
          {{ t('howTo.title') }}
        </h2>
        <p class="text-text-secondary text-base max-w-xl mx-auto">
          {{ t('howTo.desc') }}
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-6 sm:gap-8">
        <article v-for="step in steps" :key="step.number" class="relative text-center">
          <div class="w-14 h-14 rounded-2xl bg-primary/10 text-primary text-2xl font-bold flex items-center justify-center mx-auto mb-5">
            {{ step.number }}
          </div>
          <h3 class="text-lg font-semibold text-text-primary mb-2">{{ step.title }}</h3>
          <p class="text-sm text-text-secondary leading-relaxed">{{ step.desc }}</p>
          <div v-if="step.number < 3" class="hidden md:block absolute top-7 -right-4 text-border" aria-hidden="true">
            <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </article>
      </div>

      <div class="mt-10 text-center">
        <p class="text-sm text-text-muted">
          {{ t('howTo.note') }}
        </p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n.js'

const { t } = useI18n()

const steps = computed(() => t('howTo.steps').map(([title, desc], index) => ({
  number: index + 1,
  title,
  desc,
})))
</script>
