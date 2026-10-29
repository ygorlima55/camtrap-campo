"""Banco SQLite (SQLAlchemy 2). Uma tabela por conceito; datas guardadas como hora local da câmera (sem fuso)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def agora() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


class Campanha(Base):
    __tablename__ = "campanha"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    inicio: Mapped[dt.date | None] = mapped_column(Date)
    fim: Mapped[dt.date | None] = mapped_column(Date)


class Ponto(Base):
    __tablename__ = "ponto"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    observacoes: Mapped[str | None] = mapped_column(Text)


class Camera(Base):
    __tablename__ = "camera"
    id: Mapped[int] = mapped_column(primary_key=True)
    etiqueta: Mapped[str] = mapped_column(String(40), unique=True)  # P4, P7...
    modelo: Mapped[str | None] = mapped_column(String(120))
    numero_serie: Mapped[str | None] = mapped_column(String(80))
    firmware: Mapped[str | None] = mapped_column(String(80))
    observacoes: Mapped[str | None] = mapped_column(Text)
    ultimo_ponto_id: Mapped[int | None] = mapped_column(ForeignKey("ponto.id"))
    ultima_campanha_id: Mapped[int | None] = mapped_column(ForeignKey("campanha.id"))


class Importacao(Base):
    __tablename__ = "importacao"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"))
    ponto_id: Mapped[int] = mapped_column(ForeignKey("ponto.id"))
    campanha_id: Mapped[int] = mapped_column(ForeignKey("campanha.id"))
    origem: Mapped[str] = mapped_column(String(260))
    rotulo_volume: Mapped[str | None] = mapped_column(String(80))
    iniciada_em: Mapped[dt.datetime] = mapped_column(DateTime, default=agora)
    concluida_em: Mapped[dt.datetime | None] = mapped_column(DateTime)
    estado: Mapped[str] = mapped_column(String(20), default="em_andamento")  # concluida | com_erros | falhou
    total: Mapped[int] = mapped_column(Integer, default=0)
    processados: Mapped[int] = mapped_column(Integer, default=0)
    copiados: Mapped[int] = mapped_column(Integer, default=0)
    duplicados: Mapped[int] = mapped_column(Integer, default=0)
    erros: Mapped[int] = mapped_column(Integer, default=0)
    padrao_nomes: Mapped[str | None] = mapped_column(String(60))
    modelo_detectado: Mapped[str | None] = mapped_column(String(120))
    deslocamento_s: Mapped[int | None] = mapped_column(Integer)  # correção de relógio aplicada (segundos)
    mensagem: Mapped[str | None] = mapped_column(Text)

    camera: Mapped[Camera] = relationship()
    ponto: Mapped[Ponto] = relationship()
    campanha: Mapped[Campanha] = relationship()
    arquivos: Mapped[list[Arquivo]] = relationship(back_populates="importacao", order_by="Arquivo.id")
    alertas: Mapped[list[Alerta]] = relationship(back_populates="importacao", order_by="Alerta.id")


class Arquivo(Base):
    __tablename__ = "arquivo"
    id: Mapped[int] = mapped_column(primary_key=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacao.id"), index=True)
    caminho_cartao: Mapped[str] = mapped_column(String(400))  # relativo à raiz do cartão
    nome_original: Mapped[str] = mapped_column(String(260))
    tipo: Mapped[str] = mapped_column(String(12))  # foto | video | appledouble | outro
    oculto: Mapped[bool] = mapped_column(Boolean, default=False)
    tamanho: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    estado: Mapped[str] = mapped_column(String(12))  # copiado | duplicado | erro
    duplicado_de_id: Mapped[int | None] = mapped_column(ForeignKey("arquivo.id"))
    caminho_final: Mapped[str | None] = mapped_column(String(400))  # relativo à pasta Dados
    contador_original: Mapped[int | None] = mapped_column(Integer)
    data_original: Mapped[dt.datetime | None] = mapped_column(DateTime)  # relógio da câmera
    fonte_data: Mapped[str | None] = mapped_column(String(12))  # exif | rodape | video | arquivo
    data_corrigida: Mapped[dt.datetime | None] = mapped_column(DateTime)
    exif: Mapped[dict | None] = mapped_column(JSON)
    rodape: Mapped[dict | None] = mapped_column(JSON)
    rodape_diverge: Mapped[bool] = mapped_column(Boolean, default=False)
    video: Mapped[dict | None] = mapped_column(JSON)
    detalhe: Mapped[str | None] = mapped_column(Text)

    importacao: Mapped[Importacao] = relationship(back_populates="arquivos")

    @property
    def data(self) -> dt.datetime | None:
        return self.data_corrigida or self.data_original


class Alerta(Base):
    __tablename__ = "alerta"
    id: Mapped[int] = mapped_column(primary_key=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacao.id"), index=True)
    arquivo_id: Mapped[int | None] = mapped_column(ForeignKey("arquivo.id"))
    tipo: Mapped[str] = mapped_column(String(40))
    nivel: Mapped[str] = mapped_column(String(10))  # erro | aviso | info
    mensagem: Mapped[str] = mapped_column(Text)

    importacao: Mapped[Importacao] = relationship(back_populates="alertas")


class EventoCamera(Base):
    """Histórico de campo: instalação, retirada, troca de pilhas, falha, manutenção, observação."""

    __tablename__ = "evento_camera"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    data: Mapped[dt.datetime] = mapped_column(DateTime)
    ponto_id: Mapped[int | None] = mapped_column(ForeignKey("ponto.id"))
    campanha_id: Mapped[int | None] = mapped_column(ForeignKey("campanha.id"))
    pilhas_marca: Mapped[str | None] = mapped_column(String(60))
    pilhas_tipo: Mapped[str | None] = mapped_column(String(60))  # alcalina, lítio, recarregável NiMH...
    descricao: Mapped[str | None] = mapped_column(Text)
    fotos: Mapped[list | None] = mapped_column(JSON)  # caminhos relativos à pasta Dados
    registrado_em: Mapped[dt.datetime] = mapped_column(DateTime, default=agora)

    camera: Mapped[Camera] = relationship()
    ponto: Mapped[Ponto | None] = relationship()
    campanha: Mapped[Campanha | None] = relationship()


class PassoRoteiro(Base):
    """Sequência de botões para um ajuste, por modelo, partindo do reset de fábrica (configuração às cegas)."""

    __tablename__ = "passo_roteiro"
    id: Mapped[int] = mapped_column(primary_key=True)
    modelo: Mapped[str] = mapped_column(String(120), index=True)
    ordem: Mapped[int] = mapped_column(Integer)
    ajuste: Mapped[str] = mapped_column(String(120))  # ex.: "Modo: foto + vídeo"
    botoes: Mapped[str] = mapped_column(String(300))  # ex.: "MENU, ↓, ↓, OK, →, OK"
    observacao: Mapped[str | None] = mapped_column(Text)
    confirmado_em_campo: Mapped[bool] = mapped_column(Boolean, default=False)


class TesteSemTela(Base):
    """Teste de câmera com tela apagada: foto do estado do cartão antes, disparos, e comparação depois."""

    __tablename__ = "teste_sem_tela"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("camera.id"))
    raiz: Mapped[str] = mapped_column(String(260))
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, default=agora)
    antes: Mapped[list] = mapped_column(JSON)  # [[caminho, tamanho], ...] das mídias antes do teste
    verificado_em: Mapped[dt.datetime | None] = mapped_column(DateTime)
    novos: Mapped[list | None] = mapped_column(JSON)
    resultado: Mapped[str | None] = mapped_column(String(30))  # gravacao_ok | sem_novos | nao_montou
    camera: Mapped[Camera | None] = relationship()


def conectar(caminho: Path):
    """Cria o banco (se preciso) e devolve uma fábrica de sessões."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    motor = create_engine(f"sqlite:///{caminho}", connect_args={"check_same_thread": False})

    @event.listens_for(motor, "connect")
    def _pragmas(con, _):
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")  # leitura da interface enquanto a importação grava
        cur.close()

    Base.metadata.create_all(motor)
    return sessionmaker(motor, expire_on_commit=False)
