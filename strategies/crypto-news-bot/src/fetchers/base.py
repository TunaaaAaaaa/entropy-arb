from abc import ABC, abstractmethod

from ..models import NewsItem


class BaseFetcher(ABC):
    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        raise NotImplementedError
