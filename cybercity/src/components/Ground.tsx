import { useMemo } from 'react'
import * as THREE from 'three'
import type { CityModel } from '../lib/types'
import { LOT, PITCH } from '../lib/layout'
import { THEME } from '../lib/palette'

/**
 * Ground system: base plane, per-parcel sidewalk aprons + lot plates,
 * street center guide lines, and street lamps at intersections.
 */
export default function Ground({ city }: { city: CityModel }) {
  const ext = city.halfExtent

  const { sidewalks, lots } = useMemo(() => {
    const sw: Array<[number, number]> = []
    const lt: Array<[number, number]> = []
    for (const r of city.repos) {
      sw.push([r.x, r.z])
      lt.push([r.x, r.z])
    }
    return { sidewalks: sw, lots: lt }
  }, [city])

  const streetLines = useMemo(() => {
    const pts: THREE.Vector3[] = []
    const n = Math.ceil(ext / PITCH)
    for (let i = -n; i <= n; i++) {
      const c = i * PITCH + PITCH / 2
      pts.push(new THREE.Vector3(c, 0.06, -ext), new THREE.Vector3(c, 0.06, ext))
      pts.push(new THREE.Vector3(-ext, 0.06, c), new THREE.Vector3(ext, 0.06, c))
    }
    const geo = new THREE.BufferGeometry().setFromPoints(pts)
    return geo
  }, [ext])

  const lampPositions = useMemo(() => {
    const pos: Array<[number, number]> = []
    const n = Math.ceil(ext / PITCH)
    for (let i = -n; i < n; i++)
      for (let j = -n; j < n; j++) {
        if ((i + j) % 2 !== 0) continue
        pos.push([i * PITCH + PITCH / 2, j * PITCH + PITCH / 2])
      }
    return pos
  }, [ext])

  return (
    <group>
      {/* street-level base — slightly reflective dark asphalt */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[ext * 2.4, ext * 2.4]} />
        <meshStandardMaterial color={THEME.street} roughness={0.35} metalness={0.6} />
      </mesh>

      {/* sidewalk aprons */}
      {sidewalks.map(([x, z], i) => (
        <mesh key={`sw${i}`} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.05, z]}>
          <planeGeometry args={[LOT + 6, LOT + 6]} />
          <meshStandardMaterial color={THEME.sidewalk} roughness={0.8} metalness={0.1} />
        </mesh>
      ))}
      {/* lot plates */}
      {lots.map(([x, z], i) => (
        <mesh key={`lot${i}`} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.08, z]}>
          <planeGeometry args={[LOT, LOT]} />
          <meshStandardMaterial color={THEME.block} roughness={0.6} metalness={0.3} />
        </mesh>
      ))}

      {/* street guide lines */}
      <lineSegments geometry={streetLines}>
        <lineBasicMaterial color={THEME.streetLine} transparent opacity={0.8} />
      </lineSegments>

      {/* intersection street lamps — instanced: 2 draw calls total */}
      <Lamps positions={lampPositions} />
    </group>
  )
}

function Lamps({ positions }: { positions: Array<[number, number]> }) {
  const postRef = (mesh: THREE.InstancedMesh | null) => {
    if (!mesh) return
    const dummy = new THREE.Object3D()
    positions.forEach(([x, z], i) => {
      dummy.position.set(x, 2.2, z)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
  }
  const bulbRef = (mesh: THREE.InstancedMesh | null) => {
    if (!mesh) return
    const dummy = new THREE.Object3D()
    const color = new THREE.Color()
    positions.forEach(([x, z], i) => {
      dummy.position.set(x, 4.5, z)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      mesh.setColorAt(i, color.set(i % 3 === 0 ? THEME.neonCyan : THEME.neonPurple))
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }
  return (
    <group>
      <instancedMesh ref={postRef} args={[undefined, undefined, positions.length]}>
        <cylinderGeometry args={[0.09, 0.14, 4.4, 5]} />
        <meshStandardMaterial color="#171130" roughness={0.6} />
      </instancedMesh>
      <instancedMesh ref={bulbRef} args={[undefined, undefined, positions.length]}>
        <sphereGeometry args={[0.32, 8, 8]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  )
}
