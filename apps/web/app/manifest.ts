import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'GlobalInfra AI',
    short_name: 'GlobalInfra',
    description: 'Global infrastructure project intelligence and digital twin command platform.',
    start_url: '/',
    display: 'standalone',
    background_color: '#071016',
    theme_color: '#071016',
    orientation: 'portrait-primary',
    categories: ['business', 'productivity', 'utilities'],
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
    ]
  };
}
