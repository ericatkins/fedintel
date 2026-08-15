import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame } from '@react-three/fiber'
import type { CityRepo } from '../lib/types'
import { makeBillboardTexture, makeCommitPanelTexture, makeWindowTexture, makeNameSignTexture } from '../lib/billboard'
import { pseudoRandom } from '../lib/layout'
import { useCity } from '../state/store'

interface Props {
  repo: CityRepo
  dimmed: boolean
  isLandmark: boolean
  accountName: string
}

export default function Building({ repo, dimmed, isLandmark, accountName }: Props) {
  const { select, hover, hoveredRepoId, selectedRepoId } = useCity()
  const hovered = hoveredRepoId === repo.meta.id
  const selected = selectedRepoId === repo.meta.id
  const groupRef = useRef<THREE.Group>(null)
  const panelRef = useRef<THREE.Group>(null)

  const rnd = pseudoRandom(repo.meta.id)
  const h = repo.heightUnits
  const w = repo.widthUnits
  const d = repo.depthUnits
  const glow = repo.scores.glow

  const windowTex = useMemo(
    () => makeWindowTexture(repo.meta.id, repo.scores.busyness, repo.accentColor),
    [repo.meta.id, repo.scores.busyness, repo.accentColor],
  )
  const billboardTex = useMemo(() => makeBillboardTexture(repo), [repo])
  const commitTex = useMemo(() => makeCommitPanelTexture(repo), [repo])
  const nameTex = useMemo(() => (isLandmark ? makeNameSignTexture(accountName) : null), [isLandmark, accountName])

  const bodyMat = useMemo(() => {
    const mat = new THREE.MeshStandardMaterial({
      map: windowTex,
      emissive: new THREE.Color(repo.accentColor),
      emissiveMap: windowTex,
      emissiveIntensity: 0.5 + glow * 0.9,
      roughness: 0.55,
      metalness: 0.35,
    })
    return mat
  }, [windowTex, repo.accentColor, glow])

  const edgeColor = useMemo(() => new THREE.Color(repo.accentColor), [repo.accentColor])

  // gentle float on the hanging commit panel; pulse the trim when active
  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    if (panelRef.current) {
      panelRef.current.position.y = h * 0.45 + Math.sin(t * 0.8 + rnd * 10) * 0.6
    }
    if (groupRef.current) {
      const target = dimmed ? 0.25 : 1
      groupRef.current.traverse(obj => {
        const m = (obj as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined
        if (m && 'opacity' in m && (obj as any).userData.fadeable) {
          m.opacity += (target - m.opacity) * 0.12
        }
      })
    }
  })

  const opacity = dimmed ? 0.3 : 1
  const trimIntensity = (hovered || selected ? 3.2 : 1.4) + glow * 2.2

  // tiered top for taller buildings — distinct silhouettes
  const hasTier = h > 30
  const tierH = h * 0.22
  const spireH = h > 45 ? h * 0.28 : 0

  return (
    <group
      ref={groupRef}
      position={[repo.x, 0, repo.z]}
      onClick={e => {
        e.stopPropagation()
        select(repo.meta.id)
      }}
      onPointerOver={e => {
        e.stopPropagation()
        hover(repo.meta.id)
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        hover(null)
        document.body.style.cursor = 'default'
      }}
    >
      {/* main tower body */}
      <mesh position={[0, h / 2, 0]} material={bodyMat} castShadow userData={{ fadeable: true }}>
        <boxGeometry args={[w, h, d]} />
      </mesh>
      {/* neon edge trim */}
      <lineSegments position={[0, h / 2, 0]}>
        <edgesGeometry args={[new THREE.BoxGeometry(w, h, d)]} />
        <lineBasicMaterial color={edgeColor} transparent opacity={Math.min(1, 0.35 + glow * 0.8) * opacity} toneMapped={false} />
      </lineSegments>

      {/* tiered top */}
      {hasTier && (
        <mesh position={[0, h + tierH / 2, 0]} material={bodyMat} userData={{ fadeable: true }}>
          <boxGeometry args={[w * 0.6, tierH, d * 0.6]} />
        </mesh>
      )}
      {/* spire / antenna with beacon */}
      {spireH > 0 && (
        <>
          <mesh position={[0, h + tierH + spireH / 2, 0]}>
            <cylinderGeometry args={[0.25, 0.6, spireH, 6]} />
            <meshStandardMaterial color="#1a1433" emissive={edgeColor} emissiveIntensity={0.6} />
          </mesh>
          <mesh position={[0, h + tierH + spireH + 0.8, 0]}>
            <sphereGeometry args={[0.7, 12, 12]} />
            <meshBasicMaterial color={repo.accentColor} toneMapped={false} />
          </mesh>
        </>
      )}

      {/* roof glow strip */}
      <mesh position={[0, h + 0.15, 0]}>
        <boxGeometry args={[w * 0.9, 0.3, d * 0.9]} />
        <meshBasicMaterial
          color={repo.accentColor}
          toneMapped={false}
          transparent
          opacity={(0.15 + glow * 0.5) * opacity}
        />
      </mesh>

      {/* holographic billboard on the front face */}
      <mesh position={[0, h * 0.62, d / 2 + 0.35]} userData={{ fadeable: true }}>
        <planeGeometry args={[Math.min(w * 1.15, 14), Math.min(w * 1.15, 14) * 1.25]} />
        <meshBasicMaterial map={billboardTex} transparent opacity={0.96 * opacity} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>

      {/* hanging commit-traffic panel, offset to the side */}
      <group ref={panelRef} position={[w / 2 + 4.5, h * 0.45, rnd > 0.5 ? d * 0.2 : -d * 0.2]}>
        <mesh userData={{ fadeable: true }}>
          <planeGeometry args={[7, 3.5]} />
          <meshBasicMaterial map={commitTex} transparent opacity={0.92 * opacity} toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
        {/* suspension line to the building */}
        <mesh position={[-(w / 2 + 4.5) / 2 + 1.5, 1.9, 0]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.03, 0.03, w / 2 + 3, 4]} />
          <meshBasicMaterial color={repo.accentColor} transparent opacity={0.5 * opacity} toneMapped={false} />
        </mesh>
      </group>

      {/* landmark: account name sign floating above the tower */}
      {isLandmark && nameTex && (
        <mesh position={[0, h + tierH + spireH + 8, 0]} rotation={[0, 0, 0]}>
          <planeGeometry args={[26, 6.5]} />
          <meshBasicMaterial map={nameTex} transparent toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* hover/selection ground ring */}
      {(hovered || selected) && (
        <mesh position={[0, 0.12, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[Math.max(w, d) * 0.75, Math.max(w, d) * 0.75 + 1.2, 48]} />
          <meshBasicMaterial color={selected ? '#fde68a' : repo.accentColor} toneMapped={false} transparent opacity={0.9} />
        </mesh>
      )}

      {/* activity point light for busy repos */}
      {glow > 0.55 && !dimmed && (
        <pointLight position={[0, h * 0.7, 0]} color={repo.accentColor} intensity={trimIntensity * 6} distance={w * 4} decay={2} />
      )}
    </group>
  )
}
