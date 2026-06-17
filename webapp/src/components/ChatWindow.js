import Navbar from './Navbar';
import Chat from './Chat';
import EmptyChat from './EmptyChat';
import { useChat } from '../hooks/useChatRunner.js';
import SettingsButtonMobile from './Settings/SettingsButtonMobile';
import Loader from './ui/Loader';

const ChatWindow = () => {
  const { error, ready, messages, chatIdRef } = useChat();
  const hasError = error != null;
  const isReady = ready;
  const notFound = ready && chatIdRef.current && messages.length === 0;

  if (hasError) {
    return (
      <div className="relative">
        <div className="absolute w-full flex flex-row items-center justify-end mr-5 mt-5">
          <SettingsButtonMobile />
        </div>
        <div className="flex flex-col items-center justify-center min-h-screen">
          <p className="dark:text-white/70 text-black/70 text-sm">
            Failed to connect to the server. Please try again later.
          </p>
        </div>
      </div>
    );
  }

  return isReady ? (
    notFound ? (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <h1 className="text-4xl font-bold text-black/30 dark:text-white/30">
          404
        </h1>
        <p className="mt-2 dark:text-white/70 text-black/70 text-sm">
          Chat not found.
        </p>
      </div>
    ) : (
      <div>
        {messages.length > 0 ? (
          <>
            <Navbar />
            <Chat />
          </>
        ) : (
          <EmptyChat />
        )}
      </div>
    )
  ) : (
    <div className="flex items-center justify-center min-h-screen w-full">
      <Loader />
    </div>
  );
};

export default ChatWindow;
