"""Independent keyword baseline and Okapi BM25 without ML dependencies."""

from collections import Counter
import math
import re

from app.retrieval.chunks import Chunk, Hit


def tokenize(text: str) -> list[str]:
    """Normalize words consistently for lookup, BM25, and deterministic tests."""
    return re.findall(r"[a-z0-9]+",text.casefold().replace("_"," "))


def _rank(chunks: list[Chunk], scores: list[float], name: str, k: int) -> list[Hit]:
    ordered = sorted(zip(chunks,scores),key=lambda p:(-p[1],p[0].id))
    return [Hit(c,s,{name:i},{name:s}) for i,(c,s) in enumerate((p for p in ordered if p[1]>0),1)][:k]


class LookupRetriever:
    """Exact/synonym phrase matching, followed by simple keyword overlap."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

    def search(self, question: str, k: int = 6) -> list[Hit]:
        """Return deterministic matches without learned representations."""
        words = set(tokenize(question))
        phrase = " "+" ".join(tokenize(question))+" "
        scores: list[float] = []
        for chunk in self.chunks:
            aliases = chunk.metadata.get("aliases",[])
            exact = max([len(tokenize(alias)) for alias in aliases
                if " "+" ".join(tokenize(alias))+" " in phrase] or [0])
            overlap = len(words & set(tokenize(chunk.text)))
            scores.append(exact*100+overlap)
        return _rank(self.chunks,scores,"lookup",k)


class BM25Retriever:
    """Okapi BM25 with explicit k1/b and stable tie ordering."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks,self.k1,self.b = chunks,k1,b
        self.docs = [Counter(tokenize(c.text)) for c in chunks]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = sum(self.lengths)/max(len(chunks),1)
        self.df: Counter[str] = Counter(word for doc in self.docs for word in doc)

    def search(self, question: str, k: int = 6) -> list[Hit]:
        """Score catalog chunks with corpus document frequencies and length norms."""
        scores = []
        for doc,length in zip(self.docs,self.lengths):
            score = 0.0
            for word in set(tokenize(question)):
                frequency = doc[word]
                if not frequency:
                    continue
                idf = math.log(1+(len(self.docs)-self.df[word]+0.5)/(self.df[word]+0.5))
                score += idf*frequency*(self.k1+1)/(frequency+self.k1*(1-self.b+self.b*length/(self.average or 1)))
            scores.append(score)
        return _rank(self.chunks,scores,"bm25",k)
