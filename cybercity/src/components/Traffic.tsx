import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame } from '@react-three/fiber'
import type { CityModel } from '../lib/types'
import { PITCH } from '../lib/layout'
import { THEME } from '../lib/palette'

const TRAIL_COLORS = [THEME.neonCyan, THEME.neonOrange, THEME.neonMagenta, THEME.neonPurple]

/**
 * Commit-traffic light trails: glowing pulses streaming along the street grid.
 * Density scales with overall city busyness.
 */
export function LightTrails({ city }: { city: CityModel }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const ext = city.halfExtent
  const avgBusy = city.repos.reduce((a, r) => a + r.scores.busyness, 0) / Math.max(1, city.repos.length)
  const count = Math.min(260, Math.round(60 + avgBusy * 320 + city.repos.length * 6))

  const lanes = useMemo(() => {
    const n = Math.ceil(ext / PITCH)
    const arr: Array<{ axis: 'x' | 'z'; c: number; offset: number; speed: number; color: THREE.Color; scale: number }> = []
    for (let i = 0; i < count; i++) {
      const laneIdx = (i % (2 * n)) - n
      const axis = i % 2 === 0 ? 'x' : 'z'
      const side = i % 4 < 2 ? -2.6 : 2.6
      arr.push({
        axis,
        c: laneIdx * PITCH + PITCH / 2 + side,
        offset: (i * 137.5) % (ext * 2),
        speed: 14 + ((i * 61) % 30) + avgBusy * 26,
        color: new THREE.Color(TRAIL_COLORS[i % TRAIL_COLORS.length]),
        scale: 0.7 + ((i * 29) % 10) / 12,
      })
    }
    return arr
  }, [count, ext, avgBusy])

  const dummy = useMemo(() => new THREE.Object3D(), [])

  useFrame(({ clock }) => {
    const mesh = ref.current
    if (!mesh) return
    const t = clock.elapsedTime
    lanes.forEach((lane, i) => {
      const p = ((lane.offset + t * lane.speed) % (ext * 2)) - ext
      const x = lane.axis === 'x' ? p : lane.c
      const z = lane.axis === 'x' ? lane.c : p
      dummy.position.set(x, 0.35, z)
      dummy.scale.set(lane.axis === 'x' ? 3.2 * lane.scale : 0.5, 0.22, lane.axis === 'x' ? 0.5 : 3.2 * lane.scale)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      mesh.setColorAt(i, lane.color)
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={ref} args={[undefined, undefined, count]} frustumCulled={false}>
      <boxGeometry args={[1, 1, 1]} />
      <meshBasicMaterial toneMapped={false} transparent opacity={0.9} />
    </instancedMesh>
  )
}

/** Ambient drones circling the towers, with blinking beacons. */
export function Drones({ city }: { city: CityModel }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const avgBusy = city.repos.reduce((a, r) => a + r.scores.busyness, 0) / Math.max(1, city.repos.length)
  const count = Math.min(40, 8 + Math.round(avgBusy * 40) + Math.round(city.repos.length / 2))

  const paths = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => {
        const anchor = city.repos[i % city.repos.length]
        return {
          cx: anchor.x,
          cz: anchor.z,
          r: 8 + ((i * 53) % 14),
          y: anchor.heightUnits * 0.55 + ((i * 31) % 18),
          speed: 0.25 + ((i * 17) % 10) / 18,
          phase: (i * 137.5 * Math.PI) / 180,
          bob: 1 + ((i * 7) % 5) / 3,
        }
      }),
    [city, count],
  )

  const dummy = useMemo(() => new THREE.Object3D(), [])
  const color = useMemo(() => new THREE.Color(), [])

  useFrame(({ clock }) => {
    const mesh = ref.current
    if (!mesh) return
    const t = clock.elapsedTime
    paths.forEach((p, i) => {
      const a = p.phase + t * p.speed
      dummy.position.set(p.cx + Math.cos(a) * p.r, p.y + Math.sin(t * 1.7 + p.phase) * p.bob, p.cz + Math.sin(a) * p.r)
      dummy.rotation.y = -a
      dummy.scale.setScalar(1)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      const blink = Math.sin(t * 6 + i * 2.1) > 0.4 ? 1 : 0.25
      color.set(i % 3 === 0 ? THEME.neonOrange : THEME.neonCyan).multiplyScalar(blink)
      mesh.setColorAt(i, color)
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={ref} args={[undefined, undefined, count]} frustumCulled={false}>
      <boxGeometry args={[1.1, 0.35, 1.1]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}

/** Distant skyline silhouette ring so the city never ends at a hard edge. */
export function Skyline({ city }: { city: CityModel }) {
  const count = 160
  const ext = city.halfExtent

  const { geo, mat } = useMemo(() => {
    const geo = new THREE.BoxGeometry(1, 1, 1)
    const mat = new THREE.MeshStandardMaterial({
      color: '#0a0718',
      emissive: new THREE.Color(THEME.neonPurple),
      emissiveIntensity: 0.06,
      roughness: 0.9,
    })
    return { geo, mat }
  }, [])

  const matrices = useMemo(() => {
    const dummy = new THREE.Object3D()
    const out: THREE.Matrix4[] = []
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2
      const radius = ext * 1.35 + ((i * 97) % 140)
      const h = 20 + ((i * 61) % 90)
      const w = 8 + ((i * 37) % 18)
      dummy.position.set(Math.cos(a) * radius, h / 2, Math.sin(a) * radius)
      dummy.scale.set(w, h, w)
      dummy.rotation.y = a
      dummy.updateMatrix()
      out.push(dummy.matrix.clone())
    }
    return out
  }, [ext])

  return (
    <instancedMesh
      args={[geo, mat, count]}
      ref={mesh => {
        if (mesh) {
          matrices.forEach((m, i) => mesh.setMatrixAt(i, m))
          mesh.instanceMatrix.needsUpdate = true
        }
      }}
    />
  )
}
