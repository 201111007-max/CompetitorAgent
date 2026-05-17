import { defineStore } from 'pinia'
import type { HeroInfo, HeroQuery, HeroState } from '@/types/hero'

export const useHeroStore = defineStore('hero', {
  state: (): HeroState => ({
    heroes: [],
    currentQuery: null,
    isLoading: false,
    error: null
  }),

  getters: {
    heroCount: (state) => state.heroes.length,
    hasQuery: (state) => state.currentQuery !== null
  },

  actions: {
    setHeroes(heroes: HeroInfo[]) {
      this.heroes = heroes
    },

    setCurrentQuery(query: HeroQuery, saveToHistory: boolean = true) {
      this.currentQuery = query
      if (saveToHistory) {
        this.addToHistory(query)
      }
    },

    clearQuery() {
      this.currentQuery = null
    },

    setLoading(loading: boolean) {
      this.isLoading = loading
    },

    setError(error: string | null) {
      this.error = error
    },

    addToHistory(query: HeroQuery) {
      const history = this.getHistory()
      const newEntry = {
        ...query,
        timestamp: new Date().toISOString()
      }
      
      history.unshift(newEntry)
      
      if (history.length > 20) {
        history.pop()
      }
      
      localStorage.setItem('heroQueryHistory', JSON.stringify(history))
    },

    getHistory(): (HeroQuery & { timestamp: string })[] {
      try {
        const data = localStorage.getItem('heroQueryHistory')
        return data ? JSON.parse(data) : []
      } catch {
        return []
      }
    },

    clearHistory() {
      localStorage.removeItem('heroQueryHistory')
    }
  }
})
