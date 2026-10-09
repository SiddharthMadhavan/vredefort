import { Navigate, Route, Routes } from 'react-router'
import ExplorePage from './pages/ExplorePage'
export default function App() {
  return <Routes><Route path="/explore" element={<ExplorePage />} /><Route path="*" element={<Navigate to="/explore" replace />} /></Routes>
}
