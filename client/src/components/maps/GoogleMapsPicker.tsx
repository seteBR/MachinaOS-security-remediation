import React, { useEffect, useRef } from 'react';
import { loadGoogleMaps } from '../../utils/googleMapsLoader';
import { useAppTheme } from '../../hooks/useAppTheme';

interface GoogleMapsPickerProps {
  lat: number;
  lng: number;
  onLocationClick: (lat: number, lng: number) => void;
  apiKey?: string;
  zoom?: number;
  mapTypeId?: string;
  height?: string;
  width?: string;
}

const GoogleMapsPicker: React.FC<GoogleMapsPickerProps> = ({
  lat,
  lng,
  onLocationClick,
  apiKey,
  zoom = 13,
  mapTypeId = 'ROADMAP',
  height = '100%',
  width = '100%'
}) => {
  const theme = useAppTheme();
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const markerRef = useRef<google.maps.Marker | null>(null);

  useEffect(() => {
    if (!mapRef.current || !apiKey) return;

    // Load Google Maps API using centralized loader
    const loadAndInitialize = async () => {
      try {
        await loadGoogleMaps({
          apiKey,
          libraries: ['geometry']
        });
        initializeMap();
      } catch (error) {
        console.error('Failed to load Google Maps API:', error);
      }
    };

    loadAndInitialize();

    function initializeMap() {
      if (!mapRef.current || !window.google?.maps) return;

      const mapOptions: google.maps.MapOptions = {
        center: { lat, lng },
        zoom,
        mapTypeId: window.google.maps.MapTypeId[mapTypeId as keyof typeof google.maps.MapTypeId] || google.maps.MapTypeId.ROADMAP,
        clickableIcons: false,
        disableDefaultUI: false,
        zoomControl: true,
        mapTypeControl: true,
        streetViewControl: true,
        fullscreenControl: true
      };

      mapInstanceRef.current = new google.maps.Map(mapRef.current, mapOptions);

      // Create marker
      markerRef.current = new google.maps.Marker({
        position: { lat, lng },
        map: mapInstanceRef.current,
        draggable: true,
        title: 'Selected Location - Click or drag to change'
      });

      // Add click listeners
      mapInstanceRef.current.addListener('click', (e: google.maps.MapMouseEvent) => {
        if (e.latLng) {
          const newLat = e.latLng.lat();
          const newLng = e.latLng.lng();
          onLocationClick(newLat, newLng);
        }
      });

      // Add marker drag listener
      markerRef.current.addListener('dragend', (e: google.maps.MapMouseEvent) => {
        if (e.latLng) {
          const newLat = e.latLng.lat();
          const newLng = e.latLng.lng();
          onLocationClick(newLat, newLng);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onLocationClick is a callback prop; including it would tear down the map on every parent re-render.
  }, [apiKey, lat, lng, zoom, mapTypeId]);

  // Update marker position when coordinates change
  useEffect(() => {
    if (markerRef.current && mapInstanceRef.current) {
      const newPosition = { lat, lng };
      markerRef.current.setPosition(newPosition);
      mapInstanceRef.current.setCenter(newPosition);
    }
  }, [lat, lng]);

  if (!apiKey) {
    return (
      <div style={{
        height,
        width,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: theme.colors.backgroundAlt,
        color: theme.colors.textSecondary,
        fontSize: theme.fontSize.sm,
        textAlign: 'center',
        padding: theme.spacing.lg,
        border: `1px solid ${theme.colors.border}`,
        borderRadius: theme.borderRadius.sm
      }}>
        Google Maps API key required for map display
      </div>
    );
  }

  return (
    <div
      ref={mapRef}
      style={{
        height,
        width,
        border: `1px solid ${theme.colors.border}`,
        borderRadius: theme.borderRadius.sm
      }}
    />
  );
};

export default GoogleMapsPicker;