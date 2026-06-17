import { Cloud, Sun, CloudRain, CloudSnow, Wind } from 'lucide-react';
import { useEffect, useState } from 'react';

const WeatherWidget = () => {
  const [data, setData] = useState({
    temperature: 0,
    condition: '',
    location: '',
    humidity: 0,
    windSpeed: 0,
    icon: '',
    temperatureUnit: 'C',
    windSpeedUnit: 'm/s',
  });

  const [loading, setLoading] = useState(true);

  const getApproxLocation = async () => {
    const res = await fetch('https://ipwhois.app/json/');
    const data = await res.json();
    return {
      latitude: data.latitude,
      longitude: data.longitude,
      city: data.city,
    };
  };

  const getLocation = async (callback) => {
    if (navigator.geolocation) {
      const result = await navigator.permissions.query({
        name: 'geolocation',
      });
      if (result.state === 'granted') {
        navigator.geolocation.getCurrentPosition(async (position) => {
          const res = await fetch(
            `https://api-bdc.io/data/reverse-geocode-client?latitude=${position.coords.latitude}&longitude=${position.coords.longitude}&localityLanguage=en`,
            {
              method: 'GET',
              headers: { 'Content-Type': 'application/json' },
            },
          );
          const data = await res.json();
          callback({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            city: data.locality,
          });
        });
      } else if (result.state === 'prompt') {
        callback(await getApproxLocation());
        navigator.geolocation.getCurrentPosition((position) => {});
      } else if (result.state === 'denied') {
        callback(await getApproxLocation());
      }
    } else {
      callback(await getApproxLocation());
    }
  };

  const updateWeather = async () => {
    getLocation(async (location) => {
      const measureUnit = localStorage.getItem('measureUnit') ?? 'Metric';
      const isImperial = measureUnit === 'Imperial';

      const params = new URLSearchParams({
        latitude: location.latitude,
        longitude: location.longitude,
        current: 'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,is_day',
        temperature_unit: isImperial ? 'fahrenheit' : 'celsius',
        wind_speed_unit: isImperial ? 'mph' : 'kmh',
        timezone: 'auto',
      });

      const res = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`);
      if (!res.ok) {
        console.error('Error fetching weather data');
        setLoading(false);
        return;
      }
      const json = await res.json();
      const c = json.current;

      const wmoIcons = {
        0: 'clear', 1: 'clear', 2: 'cloudy-1', 3: 'cloudy-1',
        45: 'fog', 48: 'fog',
        51: 'rainy-1', 53: 'rainy-1', 55: 'rainy-2',
        61: 'rainy-2', 63: 'rainy-2', 65: 'rainy-3',
        71: 'snowy-1', 73: 'snowy-2', 75: 'snowy-3', 77: 'snowy-1',
        80: 'rainy-2', 81: 'rainy-2', 82: 'rainy-3',
        85: 'snowy-2', 86: 'snowy-3',
        95: 'scattered-thunderstorms', 96: 'severe-thunderstorm', 99: 'severe-thunderstorm',
      };

      const wmoConditions = {
        0: 'Clear', 1: 'Mostly Clear', 2: 'Partly Cloudy', 3: 'Cloudy',
        45: 'Foggy', 48: 'Rime Fog',
        51: 'Light Drizzle', 53: 'Drizzle', 55: 'Heavy Drizzle',
        61: 'Light Rain', 63: 'Rain', 65: 'Heavy Rain',
        71: 'Light Snow', 73: 'Snow', 75: 'Heavy Snow', 77: 'Snow Grains',
        80: 'Light Showers', 81: 'Showers', 82: 'Heavy Showers',
        85: 'Light Snow Showers', 86: 'Snow Showers',
        95: 'Thunderstorm', 96: 'Thunderstorm + Hail', 99: 'Severe Thunderstorm',
      };

      const code = c.weather_code ?? 0;
      const isDay = c.is_day === 1;
      const iconBase = wmoIcons[code] || 'clear';
      const icon = code >= 96 ? iconBase : `${iconBase}-${isDay ? 'day' : 'night'}`;
      const condition = wmoConditions[code] || 'Unknown';

      setData({
        temperature: Math.round(c.temperature_2m),
        condition,
        location: location.city,
        humidity: c.relative_humidity_2m ?? 0,
        windSpeed: Math.round(c.wind_speed_10m ?? 0),
        icon,
        temperatureUnit: isImperial ? 'F' : 'C',
        windSpeedUnit: isImperial ? 'mph' : 'km/h',
      });
      setLoading(false);
    });
  };

  useEffect(() => {
    updateWeather();
    const intervalId = setInterval(updateWeather, 30 * 1000);
    return () => clearInterval(intervalId);
  }, []);

  return (
    <div className="bg-light-secondary dark:bg-dark-secondary rounded-2xl border border-light-200 dark:border-dark-200 shadow-sm shadow-light-200/10 dark:shadow-black/25 flex flex-row items-center w-full h-24 min-h-[96px] max-h-[96px] px-3 py-2 gap-3">
      {loading ? (
        <>
          <div className="flex flex-col items-center justify-center w-16 min-w-16 max-w-16 h-full animate-pulse">
            <div className="h-10 w-10 rounded-full bg-light-200 dark:bg-dark-200 mb-2" />
            <div className="h-4 w-10 rounded bg-light-200 dark:bg-dark-200" />
          </div>
          <div className="flex flex-col justify-between flex-1 h-full py-1 animate-pulse">
            <div className="flex flex-row items-center justify-between">
              <div className="h-3 w-20 rounded bg-light-200 dark:bg-dark-200" />
              <div className="h-3 w-12 rounded bg-light-200 dark:bg-dark-200" />
            </div>
            <div className="h-3 w-16 rounded bg-light-200 dark:bg-dark-200 mt-1" />
            <div className="flex flex-row justify-between w-full mt-auto pt-1 border-t border-light-200 dark:border-dark-200">
              <div className="h-3 w-16 rounded bg-light-200 dark:bg-dark-200" />
              <div className="h-3 w-8 rounded bg-light-200 dark:bg-dark-200" />
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="flex flex-col items-center justify-center w-16 min-w-16 max-w-16 h-full">
            <img
              src={`/weather-ico/${data.icon}.svg`}
              alt={data.condition}
              className="h-10 w-auto"
            />
            <span className="text-base font-semibold text-black dark:text-white">
              {data.temperature}°{data.temperatureUnit}
            </span>
          </div>
          <div className="flex flex-col justify-between flex-1 h-full py-2">
            <div className="flex flex-row items-center justify-between">
              <span className="text-sm font-semibold text-black dark:text-white">
                {data.location}
              </span>
              <span className="flex items-center text-xs text-black/60 dark:text-white/60 font-medium">
                <Wind className="w-3 h-3 mr-1" />
                {data.windSpeed} {data.windSpeedUnit}
              </span>
            </div>
            <span className="text-xs text-black/50 dark:text-white/50 italic">
              {data.condition}
            </span>
            <div className="flex flex-row justify-between w-full mt-auto pt-2 border-t border-light-200/50 dark:border-dark-200/50 text-xs text-black/50 dark:text-white/50 font-medium">
              <span>Humidity {data.humidity}%</span>
              <span className="font-semibold text-black/70 dark:text-white/70">
                Now
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default WeatherWidget;
