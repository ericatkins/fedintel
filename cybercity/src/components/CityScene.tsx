import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import type { CityModel } from '../lib/types'
import { THEME } from '../lib/palette'
import { useCity, repoMatchesFilters } from '../state/store'
import Building from './Building'
import Ground from './Ground'
import { LightTrails, Drones, Skyline } from './Traffic'
import { makeNameSignTexture } from '../lib/billboard'

function CameraRig({ city }: { city: CityModel }) {
  const controls = useRef<OrbitControlsImpl>(null)
  const { camera } = useThree()
  const { cameraMode, focusRequest } = useCity()
  const lastNonce = useRef(0)
  const targetGoal = useRef(new THREE.Vector3(0, 10, 0))
  const cinematicAngle = useRef(0)

  useEffect(() => {
    if (focusRequest && focusRequest.nonce !== lastNonce.current) {
      lastNonce.current = focusRequest.nonce
      targetGoal.current.set(focusRequest.x, 12, focusRequest.z)
    }
  }, [focusRequest])

  useEffect(() => {
    if (!controls.current) return
    if (cameraMode === 'street') {
      camera.position.set(camera.position.x, 3.2, camera.position.z + 6)
    }
  }, [cameraMode, camera])

  useFrame((_, delta) => {
    const c = controls.current
    if (!c) return
    // glide target toward the focused parcel
    c.target.lerp(targetGoal.current, Math.min(1, delta * 2.5))

    if (cameraMode === 'cinematic') {
      cinematicAngle.current += delta * 0.12
      const r = city.halfExtent * 1.15
      const x = Math.cos(cinematicAngle.current) * r
      const z = Math.sin(cinematicAngle.current) * r
      const y = 55 + Math.sin(cinematicAngle.current * 0.7) * 28
      camera.position.lerp(new THREE.Vector3(x, y, z), Math.min(1, delta * 1.2))
      targetGoal.current.set(0, 14, 0)
    }
    c.update()
  })

  const street = cameraMode === 'street'
  return (
    <OrbitControls
      ref={controls}
      enableDamping
      dampingFactor={0.08}
      minDistance={street ? 2 : 18}
      maxDistance={city.halfExtent * 2.6}
      maxPolarAngle={street ? Math.PI * 0.52 : Math.PI * 0.47}
      enabled={cameraMode !== 'cinematic'}
    />
  )
}

/** Street-level marquee: "EVERY COMMIT BUILDS THE FUTURE" */
function Marquee({ city }: { city: CityModel }) {
  const tex = useMemo(() => makeNameSignTexture('EVERY COMMIT BUILDS THE FUTURE ▶'), [])
  const z = city.halfExtent * 0.55
  return (
    <group position={[0, 4, z]}>
      <mesh>
        <planeGeometry args={[34, 5]} />
        <meshBasicMaterial map={tex} transparent toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      {[-16, 16].map(x => (
        <mesh key={x} position={[x, -2.2, 0]}>
          <cylinderGeometry args={[0.16, 0.22, 4.2, 6]} />
          <meshStandardMaterial color="#171130" />
        </mesh>
      ))}
    </group>
  )
}

export default function CityScene({ city }: { city: CityModel }) {
  const { filters, select } = useCity()
  const landmarkId = city.repos.find(r => r.scores.rank === 1)?.meta.id

  const anyFilter = !!filters.language || !!filters.query

  return (
    <Canvas
      shadows={false}
      dpr={[1, 1.75]}
      camera={{ position: [city.halfExtent * 0.9, 70, city.halfExtent * 1.1], fov: 50, near: 0.5, far: 4000 }}
      gl={{ antialias: true }}
      onPointerMissed={() => select(null)}
    >
      <color attach="background" args={[THEME.sky]} />
      <fog attach="fog" args={[THEME.fog, city.halfExtent * 0.9, city.halfExtent * 4]} />

      <ambientLight intensity={0.22} color="#4c3a8f" />
      <directionalLight position={[120, 180, 80]} intensity={0.35} color="#7dd3fc" />
      <hemisphereLight args={['#2b1a5e', '#05030c', 0.5]} />

      <Stars radius={1400} depth={120} count={2400} factor={6} saturation={0.4} fade speed={0.6} />

      <Ground city={city} />
      <Skyline city={city} />
      <LightTrails city={city} />
      <Drones city={city} />
      <Marquee city={city} />

      {city.repos.map(repo => (
        <Building
          key={repo.meta.id}
          repo={repo}
          dimmed={anyFilter && !repoMatchesFilters(city, filters, repo.meta.id)}
          isLandmark={repo.meta.id === landmarkId}
          accountName={city.account.login}
        />
      ))}

      <CameraRig city={city} />

      <EffectComposer>
        <Bloom intensity={0.9} luminanceThreshold={0.18} luminanceSmoothing={0.25} mipmapBlur radius={0.75} />
        <Vignette eskil={false} offset={0.18} darkness={0.78} />
      </EffectComposer>
    </Canvas>
  )
}
