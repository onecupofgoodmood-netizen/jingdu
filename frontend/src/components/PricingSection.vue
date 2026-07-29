<template>
  <section id="pricing" class="py-16 sm:py-20 bg-white" aria-labelledby="pricing-heading">
    <div class="max-w-5xl mx-auto px-4 sm:px-6">
      <div class="text-center mb-12">
        <h2 id="pricing-heading" class="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
          {{ t('pricing.title') }}
        </h2>
        <p class="text-text-secondary text-base max-w-xl mx-auto">
          {{ t('pricing.desc') }}
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
        <!-- 免费版 -->
        <div class="bg-white rounded-2xl border border-border p-7 flex flex-col">
          <div class="mb-6">
            <h3 class="text-lg font-semibold text-text-primary mb-1">{{ t('pricing.freeName') }}</h3>
            <p class="text-sm text-text-secondary">{{ t('pricing.freeDesc') }}</p>
          </div>
          <div class="mb-6">
            <span class="text-4xl font-bold text-text-primary">¥0</span>
            <span class="text-text-muted text-sm ml-1">{{ t('pricing.forever') }}</span>
          </div>
          <ul class="space-y-3 mb-8 flex-1">
            <li v-for="item in freePlan" :key="item" class="flex items-start gap-2.5 text-sm text-text-secondary">
              <svg class="w-5 h-5 text-success flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
              {{ item }}
            </li>
          </ul>
          <button
            class="w-full h-11 rounded-full border border-border text-sm font-medium text-text-primary transition-colors"
            :class="user ? 'bg-gray-50 cursor-default' : 'hover:bg-gray-50 cursor-pointer'"
            @click="!user && $emit('need-login')"
          >
            {{ user ? t('common.currentPlan') : t('common.register') }}
          </button>
        </div>

        <!-- VIP 版 -->
        <div class="relative bg-gradient-to-br from-primary to-blue-600 rounded-2xl p-7 flex flex-col text-white overflow-hidden">
          <div class="absolute top-4 right-4 px-3 py-1 bg-white/20 rounded-full text-xs font-medium backdrop-blur-sm">
            {{ t('pricing.recommended') }}
          </div>
          <div class="absolute -top-20 -right-20 w-56 h-56 bg-white/5 rounded-full"></div>
          <div class="relative">
            <div class="mb-6">
              <h3 class="text-lg font-semibold mb-1">{{ t('pricing.vipName') }}</h3>
              <p class="text-sm text-white/70">{{ t('pricing.vipDesc') }}</p>
            </div>
            <div class="mb-6">
              <span class="text-4xl font-bold">¥9.9</span>
              <span class="text-white/70 text-sm ml-1">{{ t('pricing.perMonth') }}</span>
              <span class="ml-2 text-xs bg-white/20 px-2 py-0.5 rounded-full">{{ t('pricing.deal') }}</span>
            </div>
            <ul class="space-y-3 mb-8">
              <li v-for="item in vipPlan" :key="item" class="flex items-start gap-2.5 text-sm text-white/90">
                <svg class="w-5 h-5 text-yellow-300 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                {{ item }}
              </li>
            </ul>
            <button
              @click="handleVipClick"
              class="w-full h-11 rounded-full bg-white text-primary text-sm font-semibold hover:bg-white/90 transition-colors shadow-lg cursor-pointer"
            >
              {{ user?.is_vip ? t('common.renewVip') : t('pricing.startVip') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n.js'

const props = defineProps({
  user: { type: Object, default: null },
})

const emit = defineEmits(['open-vip', 'need-login'])
const { t } = useI18n()

const freePlan = computed(() => t('pricing.freePlan'))
const vipPlan = computed(() => t('pricing.vipPlan'))

function handleVipClick() {
  if (!props.user) {
    emit('need-login')
    return
  }
  emit('open-vip')
}
</script>
