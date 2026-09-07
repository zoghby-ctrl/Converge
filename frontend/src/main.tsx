import React from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { useRoute } from './router'
import { EntryGateway } from './EntryGateway'
import { ReportSurface } from './ReportSurface'
import { OperationsWorkbench } from './OperationsWorkbench'

function App() {
  const [route] = useRoute()

  if (route === '/report') {
    return <ReportSurface />
  }

  if (route === '/operations') {
    return <OperationsWorkbench />
  }

  return <EntryGateway />
}

createRoot(document.getElementById('root')!).render(<App />)
