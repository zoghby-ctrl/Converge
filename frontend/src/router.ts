import { useState, useEffect } from 'react'

export type Route = '/' | '/report' | '/operations'

export function normalizePath(path: string): Route {
  if (path.startsWith('/report')) return '/report'
  if (path.startsWith('/operations')) return '/operations'
  return '/'
}

export function navigate(to: Route) {
  if (window.location.pathname !== to) {
    window.history.pushState({}, '', to)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }
}

export function useRoute(): [Route, (to: Route) => void] {
  const [route, setRoute] = useState<Route>(() => normalizePath(window.location.pathname))

  useEffect(() => {
    const handlePopState = () => {
      setRoute(normalizePath(window.location.pathname))
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  return [route, navigate]
}
