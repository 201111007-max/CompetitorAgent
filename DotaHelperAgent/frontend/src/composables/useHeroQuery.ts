import { useHeroStore } from '@/stores/hero'
import type { HeroInfo, HeroQuery } from '@/types/hero'

// 使用相对路径，通过 Vite 代理转发到后端
const baseURL = import.meta.env.VITE_API_BASE_URL || ''

export function useHeroQuery() {
  const heroStore = useHeroStore()

  const generateQuery = async (retryCount = 0): Promise<HeroQuery | null> => {
    const maxRetries = 2
    heroStore.setLoading(true)
    heroStore.setError(null)

    try {
      const response = await fetch(`${baseURL}/api/generate_hero_query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })

      // 检查 HTTP 状态码
      if (!response.ok) {
        const contentType = response.headers.get('content-type') || ''
        // 如果返回的是 HTML（proxy 错误页面），尝试重试
        if (contentType.includes('text/html') && retryCount < maxRetries) {
          console.warn(`请求失败 (HTTP ${response.status})，重试中... (${retryCount + 1}/${maxRetries})`)
          await new Promise(resolve => setTimeout(resolve, 500 * (retryCount + 1)))
          return generateQuery(retryCount + 1)
        }
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      // 检查响应类型
      const contentType = response.headers.get('content-type') || ''
      if (!contentType.includes('application/json')) {
        if (retryCount < maxRetries) {
          console.warn(`响应类型错误 (${contentType})，重试中... (${retryCount + 1}/${maxRetries})`)
          await new Promise(resolve => setTimeout(resolve, 500 * (retryCount + 1)))
          return generateQuery(retryCount + 1)
        }
        throw new Error('服务器返回了非 JSON 响应')
      }

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
      // 网络错误，尝试重试
      if (retryCount < maxRetries) {
        console.warn(`网络错误，重试中... (${retryCount + 1}/${maxRetries})`, e)
        await new Promise(resolve => setTimeout(resolve, 500 * (retryCount + 1)))
        return generateQuery(retryCount + 1)
      }
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
