import { useHeroStore } from '@/stores/hero'
import type { HeroInfo, HeroQuery } from '@/types/hero'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

export function useHeroQuery() {
  const heroStore = useHeroStore()

  const generateQuery = async (): Promise<HeroQuery | null> => {
    heroStore.setLoading(true)
    heroStore.setError(null)

    try {
      const response = await fetch(`${baseURL}/api/generate_hero_query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })

      const data = await response.json()

      if (data.success) {
        const query: HeroQuery = {
          query: data.query,
          our_heroes: data.our_heroes,
          enemy_heroes: data.enemy_heroes
        }
        heroStore.setCurrentQuery(query)
        return query
      } else {
        heroStore.setError(data.error || '生成查询失败')
        return null
      }
    } catch (e) {
      const error = e instanceof Error ? e.message : '网络错误'
      heroStore.setError(error)
      return null
    } finally {
      heroStore.setLoading(false)
    }
  }

  const clearQuery = () => {
    heroStore.clearQuery()
  }

  return {
    generateQuery,
    clearQuery
  }
}

export async function fetchHeroes(): Promise<HeroInfo[]> {
  try {
    const response = await fetch(`${baseURL}/data/heroes_cn.json`)
    const data = await response.json()
    
    const heroes: HeroInfo[] = Object.entries(data).map(([id, info]: [string, any]) => ({
      id,
      cn: info.cn,
      en: info.en
    }))
    
    return heroes
  } catch (e) {
    console.error('Failed to fetch heroes:', e)
    return []
  }
}
