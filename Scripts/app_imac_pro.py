import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

# --- 1. CONFIGURAÇÃO DE LOGGING (Auditoria) ---
# Em produção, isso iria para um arquivo .log
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. CONFIGURAÇÃO DA PÁGINA E SEO ---
st.set_page_config(
    page_title="GeoData Hub | IMAC-ICV",  # Título na aba do navegador (SEO)
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': 'https://github.com/seu-repo/issues',
        'Report a bug': "mailto:geotecnologia@icv.org.br",
        'About': "Portal de automação de dados geográficos do ICV."
    }
)

# --- CONSTANTES DE SEGURANÇA ---
# Headers para simular navegador real e evitar bloqueio (WAF bypass simples)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}


# --- 3. CORE LOGIC COM CACHE (O Pulo do Gato) ---

@st.cache_data(ttl=3600, show_spinner=False)
def obter_links_download():
    """
    Scraper que roda apenas 1 vez por hora (TTL=3600s).
    Isso protege nosso IP de ser banido pelo IMAC por excesso de requisições.
    Retorna: Lista de dicionários com metadata dos arquivos (não o binário).
    """
    logger.info("Iniciando varredura no site do IMAC (Cache Miss)")

    tarefas = [
        {
            "nome": "LICENCIAMENTO",
            "url": "https://imac.ac.gov.br/licenciamento/",
            "alvos": {
                "SUPRESSAO": "imac_supressao.zip",
                "USO-ALTERNATIVO": "imac_uso_alternativo.zip"
            }
        },
        {
            "nome": "FISCALIZACAO",
            "url": "https://imac.ac.gov.br/fiscalizacao-autuacoes/",
            "alvos": {
                "Embargos_Adm_IMAC_2025": "imac_embargos_2025.zip",
                "Embargos_adm_IMAC_2024": "imac_embargos_2024.zip"
            }
        }
    ]

    links_para_baixar = []

    for tarefa in tarefas:
        try:
            r = requests.get(tarefa['url'], headers=HEADERS, timeout=15)  # Timeout é CRUCIAL para segurança
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', href=True)

            for termo, nome_final in tarefa['alvos'].items():
                for link in links:
                    href = link['href']
                    text = link.get_text().strip()

                    # Lógica de Matching (HREF ou Texto)
                    match_found = (termo.upper() in href.upper()) or (termo.upper() in text.upper())
                    is_zip = href.lower().endswith(('.zip', '.rar'))

                    if match_found and is_zip:
                        full_url = urljoin(tarefa['url'], href)
                        links_para_baixar.append({
                            "url": full_url,
                            "filename": nome_final,
                            "origem": tarefa['nome']
                        })
                        break  # Para de procurar este termo na página
        except Exception as e:
            logger.error(f"Erro ao varrer {tarefa['url']}: {e}")
            # Não quebra o app, apenas loga o erro e continua
            continue

    return links_para_baixar


def processar_downloads(lista_links):
    """
    Executa o download físico e compactação.
    Usa diretório temporário seguro.
    """
    # Cria pasta temporária segura (OS handles cleanup mostly, but we force it)
    temp_dir = Path(tempfile.mkdtemp())
    download_dir = temp_dir / "dados_imac"
    download_dir.mkdir()

    log_execucao = []
    sucesso_count = 0

    progresso = st.progress(0)

    for idx, item in enumerate(lista_links):
        url = item['url']
        fname = item['filename']
        path_destino = download_dir / fname

        try:
            logger.info(f"Baixando: {fname}")
            with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(path_destino, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)

            log_execucao.append(f"✅ **{fname}**: Sucesso ({item['origem']})")
            sucesso_count += 1

        except Exception as e:
            log_execucao.append(f"❌ **{fname}**: Falha no download")
            logger.error(f"Falha download {fname}: {e}")

        progresso.progress((idx + 1) / len(lista_links))

    # Compactação Final
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    nome_zip = f"Geodata_IMAC_{timestamp}"

    # Gera o ZIP
    caminho_zip = shutil.make_archive(
        base_name=str(temp_dir / nome_zip),
        format='zip',
        root_dir=download_dir
    )

    return caminho_zip, log_execucao, temp_dir


# --- 4. INTERFACE DO USUÁRIO (Frontend) ---

st.title("🌍 GeoData Hub")
st.markdown("### Monitoramento Automático de Bases do IMAC")
st.info("ℹ️ **Cache Ativo:** O sistema verifica atualizações no site do IMAC a cada 60 minutos para evitar bloqueios.")

col1, col2 = st.columns([1, 2])

with col1:
    if st.button("🚀 Iniciar Processamento", type="primary", use_container_width=True):
        with st.status("Processando...", expanded=True) as status:

            # Passo 1: Obter URLs (Usa Cache se disponível)
            st.write("🔍 Verificando site do IMAC...")
            links = obter_links_download()

            if not links:
                status.update(label="Nenhum link encontrado ou erro de conexão.", state="error")
                st.error("Não foi possível localizar os arquivos. Verifique os logs.")
            else:
                st.write(f"📂 {len(links)} arquivos identificados. Iniciando download...")

                # Passo 2: Download Físico (Sempre acontece para gerar o ZIP novo)
                zip_path, logs, temp_folder = processar_downloads(links)

                # Exibir Logs na UI
                for log in logs:
                    st.write(log)

                status.update(label="Processamento Concluído!", state="complete")

                # Passo 3: Botão de Download
                with open(zip_path, "rb") as fp:
                    st.success("Pacote pronto para download.")
                    st.download_button(
                        label="📥 BAIXAR PACOTE UNIFICADO (.ZIP)",
                        data=fp,
                        file_name=os.path.basename(zip_path),
                        mime="application/zip",
                        type="primary"
                    )

                # Cleanup (Segurança de Disco)
                # Removemos a pasta temporária após ler o arquivo para memória
                # Nota: Em apps muito grandes, isso deve ser feito com cuidado.
                try:
                    shutil.rmtree(temp_folder)
                    logger.info(f"Limpeza realizada: {temp_folder}")
                except Exception as e:
                    logger.warning(f"Não foi possível limpar temp: {e}")

st.divider()
st.caption("🔒 Ambiente Seguro | Núcleo de Inteligência Territorial - ICV")