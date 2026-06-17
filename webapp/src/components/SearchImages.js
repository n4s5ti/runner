import { ImagesIcon } from 'lucide-react';

const SearchImages = () => (
  <div className="border border-dashed border-light-200 dark:border-dark-200 px-4 py-2 flex flex-row items-center justify-between rounded-lg dark:text-white text-sm w-full">
    <div className="flex flex-row items-center space-x-2">
      <ImagesIcon size={17} />
      <p>Image search coming soon</p>
    </div>
  </div>
);

export default SearchImages;
