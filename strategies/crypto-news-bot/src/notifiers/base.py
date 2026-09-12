from abc import ABC, abstractmethod


class BaseNotifier(ABC):
    delivery_key = None

    def start(self):
        pass

    def close(self):
        pass

    @abstractmethod
    def send(self, message: str) -> bool:
        raise NotImplementedError
