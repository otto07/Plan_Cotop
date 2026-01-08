import streamlit as st
import pandas as pd
import time
import logging
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException

# =============================================================================
# CONFIGURAÇÕES DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Robô ANTT - Cloud Pro", 
    page_icon="🚛", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# CONFIGURAÇÕES GLOBAIS
# =============================================================================
@dataclass
class Config:
    """Configurações centralizadas da aplicação"""
    url_login: str = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
    timeout_elemento: int = 20
    
    # Colunas da Planilha
    col_auto: str = 'Auto de Infração'
    col_processo: str = 'Nº do Processo'
    col_data: str = 'Data da Infração'
    col_codigo: str = 'Código da Infração'
    col_fato: str = 'Fato Gerador'
    col_andamento: str = 'Último Andamento'
    col_data_andamento: str = 'Data do Último Andamento'
    col_status: str = 'Status Consulta'

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("ANTT_Bot")

# Modo Debug Global
DEBUG_MODE = st.sidebar.checkbox("🐛 Modo Debug Avançado", value=False, 
                                  help="Ativa screenshots e logs detalhados")

# =============================================================================
# GERENCIADOR DE DRIVER
# =============================================================================
class WebDriverManager:
    """Gerencia criação e configuração do Chrome WebDriver"""
    
    @staticmethod
    def criar_driver(headless: bool = True):
        """Cria instância do Chrome WebDriver otimizada para Streamlit Cloud"""
        chrome_options = Options()
        
        # Binários do Streamlit Cloud (instalados via packages.txt)
        chrome_options.binary_location = "/usr/bin/chromium"
        
        # Modo headless condicional
        if headless:
            chrome_options.add_argument("--headless=new")
            st.sidebar.info("🤖 Modo: Headless (automático)")
        else:
            st.sidebar.warning("👁️ Modo: Visual (debug)")
        
        # Flags essenciais para container Linux
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Anti-detecção
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # User-Agent realista
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Remove propriedades de automação
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver
        except Exception as e:
            st.error(f"❌ Erro ao iniciar navegador: {e}")
            st.stop()

# =============================================================================
# GERENCIADOR DE LOGIN (VERSÃO DEFINITIVA COM STALE ELEMENT FIX)
# =============================================================================
class LoginManager:
    """Gerencia autenticação no sistema ANTT com tratamento correto de postback ASP.NET"""
    
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config
    
    def _tirar_screenshot_debug(self, nome: str):
        """Captura screenshot para debug no Streamlit"""
        if DEBUG_MODE:
            try:
                screenshot = self.driver.get_screenshot_as_png()
                st.image(screenshot, caption=f"🔍 Debug: {nome}", use_container_width=True)
            except Exception as e:
                st.warning(f"Não foi possível capturar screenshot: {e}")
    
    def _aguardar_carga_dinamica(self, timeout: int = 10):
        """Aguarda todas as cargas dinâmicas (AJAX/jQuery/JS) completarem"""
        try:
            def carga_completa(driver):
                """Verifica se todas as cargas assíncronas terminaram"""
                jquery_completo = True
                js_completo = False
                
                # Verifica jQuery (se existir)
                try:
                    if driver.execute_script("return typeof jQuery !== 'undefined'"):
                        jquery_completo = driver.execute_script("return jQuery.active") == 0
                except:
                    jquery_completo = True
                
                # Verifica JavaScript
                try:
                    js_completo = driver.execute_script("return document.readyState") == 'complete'
                except:
                    js_completo = False
                
                return jquery_completo and js_completo
            
            WebDriverWait(self.driver, timeout).until(carga_completa)
            
            if DEBUG_MODE:
                st.success("✅ Carga dinâmica completa (jQuery + JS)")
                
        except Exception as e:
            if DEBUG_MODE:
                st.warning(f"Timeout na carga dinâmica: {e}")
    
    def _aguardar_elemento_ficar_stale_e_reaparecer(self, elemento_id: str, timeout: int = 15):
        """
        Técnica definitiva para postback ASP.NET:
        1. Aguarda elemento ficar stale (obsoleto)
        2. Aguarda elemento reaparecer
        3. Retorna novo elemento válido
        """
        try:
            # Passo 1: Captura referência do elemento ANTES do postback
            elemento_antigo = self.driver.find_element(By.ID, elemento_id)
            
            if DEBUG_MODE:
                st.info(f"📍 Rastreando elemento: {elemento_id}")
            
            # Passo 2: Aguarda elemento ficar STALE (sinal de que postback aconteceu)
            try:
                WebDriverWait(self.driver, timeout).until(
                    EC.staleness_of(elemento_antigo)
                )
                if DEBUG_MODE:
                    st.success("✅ Elemento ficou stale (postback detectado)")
            except:
                if DEBUG_MODE:
                    st.warning("⚠️ Elemento não ficou stale (pode não ter havido postback)")
            
            # Passo 3: Aguarda carga dinâmica completar
            self._aguardar_carga_dinamica(timeout=10)
            
            # Passo 4: Busca elemento novamente (agora válido após postback)
            time.sleep(1)  # Delay adicional para garantir
            novo_elemento = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.ID, elemento_id))
            )
            
            if DEBUG_MODE:
                st.success(f"✅ Elemento reapareceu: {elemento_id}")
            
            return novo_elemento
            
        except Exception as e:
            if DEBUG_MODE:
                st.error(f"❌ Erro ao aguardar staleness: {e}")
            return None
    
    def _inserir_texto_robusto(self, elemento, texto: str, max_tentativas: int = 3) -> bool:
        """Insere texto com múltiplas estratégias e verificação"""
        for tentativa in range(max_tentativas):
            try:
                # Limpa o campo
                elemento.clear()
                time.sleep(0.3)
                
                # Clica e foca
                elemento.click()
                time.sleep(0.2)
                
                # Insere texto
                elemento.send_keys(texto)
                time.sleep(0.5)
                
                # Verifica se foi inserido
                valor_atual = elemento.get_attribute('value')
                
                if len(valor_atual) >= len(texto) * 0.9:  # 90% do tamanho
                    if DEBUG_MODE:
                        st.success(f"✅ Texto inserido: {len(valor_atual)} caracteres")
                    return True
                
                # Fallback: JavaScript
                if tentativa == max_tentativas - 1:
                    self.driver.execute_script(
                        f"arguments[0].value = '{texto}';", elemento
                    )
                    
                    # Dispara eventos
                    self.driver.execute_script("""
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                        arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
                    """, elemento)
                    
                    time.sleep(0.5)
                    
                    valor_atual = elemento.get_attribute('value')
                    if len(valor_atual) > 0:
                        if DEBUG_MODE:
                            st.info("✅ Texto inserido via JavaScript")
                        return True
                
            except StaleElementReferenceException:
                if DEBUG_MODE:
                    st.warning(f"⚠️ Elemento stale na tentativa {tentativa+1}")
                time.sleep(1)
                continue
            
            except Exception as e:
                if DEBUG_MODE:
                    st.warning(f"⚠️ Tentativa {tentativa+1} falhou: {e}")
                time.sleep(1)
        
        return False
    
    def realizar_login(self, usuario: str, senha: str) -> bool:
        """Processo completo de login com tratamento correto de postback ASP.NET"""
        
        try:
            st.info("🌐 Acessando página de login...")
            self.driver.get(self.config.url_login)
            time.sleep(3)
            
            self._tirar_screenshot_debug("01 - Página Inicial")
            
            # ============================================================
            # ETAPA 1: INSERIR USUÁRIO
            # ============================================================
            st.info("👤 Inserindo usuário...")
            
            id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
            
            campo_user = self.wait.until(
                EC.element_to_be_clickable((By.ID, id_user))
            )
            
            if not self._inserir_texto_robusto(campo_user, usuario):
                st.error("❌ Falha ao inserir usuário")
                return False
            
            st.success("✅ Usuário inserido")
            self._tirar_screenshot_debug("02 - Usuário OK")
            
            # ============================================================
            # ETAPA 2: CLICAR BOTÃO OK E AGUARDAR POSTBACK
            # ============================================================
            st.info("▶️ Clicando botão OK e aguardando postback ASP.NET...")
            
            id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
            
            btn_ok = self.wait.until(
                EC.element_to_be_clickable((By.ID, id_btn_ok))
            )
            
            # Scroll até o botão
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", btn_ok
            )
            time.sleep(0.5)
            
            # CLICA NO BOTÃO (vai causar postback)
            try:
                btn_ok.click()
                if DEBUG_MODE:
                    st.info("✅ Clique executado")
            except:
                self.driver.execute_script("arguments[0].click();", btn_ok)
                if DEBUG_MODE:
                    st.info("✅ Clique via JavaScript")
            
            time.sleep(1)
            
            # ============================================================
            # ETAPA 3: AGUARDAR CAMPO DE SENHA FICAR STALE E REAPARECER
            # ============================================================
            st.info("⏳ Aguardando postback completar...")
            
            # IDs possíveis para o campo de senha
            ids_senha_possiveis = [
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxSenha",
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txtSenha",
                "TextBoxSenha"
            ]
            
            campo_senha = None
            id_senha_encontrado = None
            
            # Aguarda carga dinâmica completar
            self._aguardar_carga_dinamica(timeout=15)
            time.sleep(2)
            
            self._tirar_screenshot_debug("03 - Após postback")
            
            # ============================================================
            # ETAPA 4: LOCALIZAR CAMPO DE SENHA
            # ============================================================
            st.info("🔒 Localizando campo de senha...")
            
            # Método 1: Por tipo password
            try:
                campo_senha = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='password']"))
                )
                st.success("✅ Campo senha encontrado (tipo password)")
                self._tirar_screenshot_debug("04 - Campo senha encontrado")
            except:
                pass
            
            # Método 2: Por IDs possíveis
            if not campo_senha:
                for id_possivel in ids_senha_possiveis:
                    try:
                        campo_senha = self.driver.find_element(By.ID, id_possivel)
                        id_senha_encontrado = id_possivel
                        st.success(f"✅ Campo senha encontrado: {id_possivel}")
                        break
                    except:
                        continue
            
            # Método 3: Por name
            if not campo_senha:
                try:
                    campo_senha = self.driver.find_element(
                        By.NAME,
                        "ctl00$ctl00$ctl00$ctl00$ContentPlaceHolderCorpo$ContentPlaceHolderCorpo$ContentPlaceHolderCorpo$ContentPlaceHolderCorpo$TextBoxSenha"
                    )
                    st.success("✅ Campo senha encontrado (por name)")
                except:
                    pass
            
            # Se não encontrou, mostra todos os inputs para debug
            if not campo_senha:
                st.error("❌ Campo de senha NÃO encontrado")
                self._tirar_screenshot_debug("ERRO - Campo senha não encontrado")
                
                if DEBUG_MODE:
                    with st.expander("🔧 Todos os campos INPUT da página"):
                        inputs = self.driver.find_elements(By.TAG_NAME, "input")
                        for idx, inp in enumerate(inputs):
                            tipo = inp.get_attribute('type') or 'N/A'
                            id_inp = inp.get_attribute('id') or 'N/A'
                            name_inp = inp.get_attribute('name') or 'N/A'
                            visivel = inp.is_displayed()
                            st.code(f"{idx+1}. Type: {tipo} | ID: {id_inp} | Name: {name_inp} | Visível: {visivel}")
                
                return False
            
            # ============================================================
            # ETAPA 5: INSERIR SENHA
            # ============================================================
            st.info("🔑 Inserindo senha...")
            
            # Aguarda campo estar visível
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.visibility_of(campo_senha)
                )
            except:
                pass
            
            time.sleep(1)
            
            if not self._inserir_texto_robusto(campo_senha, senha):
                st.error("❌ Falha ao inserir senha")
                self._tirar_screenshot_debug("ERRO - Falha senha")
                return False
            
            # Verifica se foi inserido
            tamanho = len(campo_senha.get_attribute('value') or '')
            
            if tamanho == 0:
                st.error("❌ Campo de senha está vazio")
                self._tirar_screenshot_debug("ERRO - Senha vazia")
                return False
            
            st.success(f"✅ Senha inserida ({tamanho} caracteres)")
            self._tirar_screenshot_debug("05 - Senha inserida")
            
            time.sleep(1)
            
            # ============================================================
            # ETAPA 6: SUBMETER FORMULÁRIO
            # ============================================================
            st.info("📤 Enviando formulário...")
            
            # Tenta encontrar botão de login
            botao_login_ids = [
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonLogin",
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnEntrar",
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_Button1",
                "ButtonLogin"
            ]
            
            botao_encontrado = False
            
            for btn_id in botao_login_ids:
                try:
                    btn_login = self.driver.find_element(By.ID, btn_id)
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", btn_login)
                    time.sleep(0.5)
                    
                    try:
                        btn_login.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", btn_login)
                    
                    st.success(f"✅ Botão login clicado: {btn_id}")
                    botao_encontrado = True
                    break
                except:
                    continue
            
            # Fallback: ENTER
            if not botao_encontrado:
                st.info("⌨️ Enviando ENTER no campo de senha")
                campo_senha.send_keys(Keys.RETURN)
            
            # Aguarda processamento
            st.info("⏳ Aguardando autenticação...")
            time.sleep(5)
            
            self._aguardar_carga_dinamica(timeout=15)
            
            self._tirar_screenshot_debug("06 - Após submeter")
            
            # ============================================================
            # ETAPA 7: VERIFICAR SUCESSO
            # ============================================================
            st.info("🔍 Verificando autenticação...")
            
            try:
                campo_consulta = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                    )
                )
                
                st.success("✅ Login realizado com sucesso!")
                self._tirar_screenshot_debug("07 - LOGIN SUCESSO")
                return True
                
            except:
                st.error("❌ Falha na autenticação")
                self._tirar_screenshot_debug("08 - FALHA LOGIN")
                
                # Diagnóstico
                try:
                    url_atual = self.driver.current_url
                    titulo = self.driver.title
                    
                    st.warning(f"**URL atual:** {url_atual}")
                    st.warning(f"**Título:** {titulo}")
                    
                    page_source = self.driver.page_source.lower()
                    
                    if "incorreta" in page_source or "inválid" in page_source:
                        st.error("🚫 Credenciais incorretas")
                    elif "captcha" in page_source:
                        st.error("🚫 CAPTCHA detectado")
                    else:
                        st.error("🚫 Erro desconhecido")
                    
                    if DEBUG_MODE:
                        with st.expander("🔧 HTML da página (primeiros 3000 chars)"):
                            st.code(self.driver.page_source[:3000], language="html")
                
                except Exception as diag_error:
                    st.error(f"Erro no diagnóstico: {diag_error}")
                
                return False
        
        except Exception as e:
            st.error(f"❌ Erro fatal: {e}")
            self._tirar_screenshot_debug("ERRO FATAL")
            
            if DEBUG_MODE:
                st.exception(e)
            
            return False

# =============================================================================
# CONSULTOR ANTT
# =============================================================================
class ConsultorANTT:
    """Realiza consultas no sistema ANTT"""
    
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config
    
    def _esperar_dados_preenchidos(self, element_id: str, timeout: int = 10) -> str:
        """Aguarda campo ser preenchido dinamicamente via AJAX"""
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            try:
                elem = self.driver.find_element(By.ID, element_id)
                valor = elem.get_attribute('value')
                
                if valor and valor.strip():
                    return valor
                
                time.sleep(0.5)
            except:
                pass
        
        return ""
    
    def processar_auto(self, auto_infracao: str) -> Dict[str, Any]:
        """Processa consulta de um auto de infração"""
        
        resultado = {
            'status': 'erro',
            'dados': {},
            'mensagem': ''
        }
        
        janela_principal = self.driver.current_window_handle
        
        try:
            # ========== 1. INSERIR NÚMERO DO AUTO ==========
            campo_busca = self.wait.until(
                EC.element_to_be_clickable(
                    (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                )
            )
            
            campo_busca.clear()
            time.sleep(0.3)
            campo_busca.send_keys(auto_infracao)
            time.sleep(0.5)
            
            # ========== 2. PESQUISAR (COM RETRY) ==========
            encontrou = False
            
            for tentativa in range(3):
                try:
                    btn_pesquisar = self.driver.find_element(
                        By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar"
                    )
                    
                    self.driver.execute_script("arguments[0].click();", btn_pesquisar)
                    time.sleep(2)
                    
                    # Aguarda resultado
                    self.wait.until(
                        EC.presence_of_element_located(
                            (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
                        )
                    )
                    
                    encontrou = True
                    break
                    
                except:
                    # Verifica se não encontrou registro
                    if "Nenhum registro encontrado" in self.driver.page_source:
                        break
                    
                    if DEBUG_MODE and tentativa < 2:
                        st.warning(f"Tentativa {tentativa+1} falhou, repetindo...")
            
            if not encontrou:
                resultado['status'] = 'nao_encontrado'
                resultado['mensagem'] = 'Auto não localizado'
                return resultado
            
            # ========== 3. ABRIR POPUP DE DETALHES ==========
            btn_editar = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0"
            )
            
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", 
                btn_editar
            )
            time.sleep(1)
            
            self.driver.execute_script("arguments[0].click();", btn_editar)
            
            # ========== 4. TROCAR PARA JANELA POPUP ==========
            WebDriverWait(self.driver, 15).until(EC.number_of_windows_to_be(2))
            
            janelas = self.driver.window_handles
            nova_janela = [j for j in janelas if j != janela_principal][0]
            
            self.driver.switch_to.window(nova_janela)
            time.sleep(3)
            
            # ========== 5. EXTRAIR DADOS ==========
            dados = self._extrair_dados_popup()
            
            if dados:
                resultado['status'] = 'sucesso'
                resultado['dados'] = dados
                resultado['mensagem'] = 'Sucesso'
            else:
                resultado['mensagem'] = 'Erro ao extrair dados'
            
            # ========== 6. FECHAR POPUP ==========
            self.driver.close()
            self.driver.switch_to.window(janela_principal)
            
            return resultado
        
        except Exception as e:
            resultado['mensagem'] = f'Erro: {str(e)[:100]}'
            
            # Garante retorno à janela principal
            if len(self.driver.window_handles) > 1:
                try:
                    self.driver.close()
                    self.driver.switch_to.window(janela_principal)
                except:
                    pass
            
            return resultado
    
    def _extrair_dados_popup(self) -> Dict[str, str]:
        """Extrai todos os dados do popup de detalhes"""
        
        dados = {}
        
        try:
            # ========== CAMPOS BÁSICOS ==========
            id_processo = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            
            self.wait.until(EC.visibility_of_element_located((By.ID, id_processo)))
            
            # Processo (com espera de preenchimento AJAX)
            dados['processo'] = self._esperar_dados_preenchidos(id_processo) or \
                               self.driver.find_element(By.ID, id_processo).get_attribute('value')
            
            # Data da Infração
            dados['data_infracao'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao"
            ).get_attribute('value')
            
            # Código da Infração
            dados['codigo'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao"
            ).get_attribute('value')
            
            # Fato Gerador
            dados['fato'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao"
            ).get_attribute('value')
            
            # ========== TABELA DE ANDAMENTOS ==========
            self._extrair_andamentos(dados)
            
            return dados
        
        except Exception as e:
            if DEBUG_MODE:
                st.error(f"Erro na extração: {e}")
            return {}
    
    def _extrair_andamentos(self, dados: Dict[str, str]):
        """Extrai última linha da tabela de andamentos processuais"""
        
        try:
            xpath_tabela = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
            
            self.wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
            
            tabela = self.driver.find_element(By.XPATH, xpath_tabela)
            linhas = tabela.find_elements(By.TAG_NAME, "tr")
            
            if len(linhas) > 1:  # Tem dados além do cabeçalho
                ultima_linha = linhas[-1]
                cols = ultima_linha.find_elements(By.TAG_NAME, "td")
                
                if len(cols) >= 4:
                    # Estrutura esperada: [Col1] [Descrição] [Col3] [Data]
                    dados['andamento'] = cols[1].text.strip()
                    dados['data_andamento'] = cols[3].text.strip()
                
                elif len(cols) >= 2:
                    # Fallback para estruturas diferentes
                    dados['andamento'] = cols[0].text.strip()
                    dados['data_andamento'] = cols[-1].text.strip()
                
                else:
                    dados['andamento'] = "Formato desconhecido"
                    dados['data_andamento'] = ""
            
            else:
                dados['andamento'] = "Sem andamentos"
                dados['data_andamento'] = ""
        
        except Exception as e:
            if DEBUG_MODE:
                st.warning(f"Erro ao ler tabela: {e}")
            
            dados['andamento'] = 'Erro na tabela'
            dados['data_andamento'] = ""

# =============================================================================
# PROCESSAMENTO DA PLANILHA
# =============================================================================
def processar_planilha(arquivo, usuario: str, senha: str, config: Config):
    """Fluxo completo de processamento da planilha"""
    
    try:
        # ========== 1. CARREGAR PLANILHA ==========
        with st.spinner("📊 Carregando planilha..."):
            df = pd.read_excel(arquivo)
            
            # Validar coluna obrigatória
            if config.col_auto not in df.columns:
                st.error(f"❌ Coluna '{config.col_auto}' não encontrada!")
                st.info("**Colunas disponíveis:** " + ", ".join(df.columns.tolist()))
                return
            
            # Criar colunas de saída se não existirem
            colunas_saida = [
                config.col_processo, config.col_data, config.col_codigo,
                config.col_fato, config.col_andamento, config.col_data_andamento,
                config.col_status
            ]
            
            for col in colunas_saida:
                if col not in df.columns:
                    df[col] = ""
            
            # Limpar valores vazios
            df = df.astype(object).replace('nan', '').fillna('')
            
            # Filtrar apenas linhas com auto válido
            df_filtrado = df[
                df[config.col_auto].notna() & 
                (df[config.col_auto].astype(str).str.strip() != '')
            ]
            
            total = len(df_filtrado)
            
            if total == 0:
                st.warning("⚠️ Nenhum auto de infração encontrado na planilha")
                return
            
            st.success(f"✅ {total} autos de infração para processar")
        
        # ========== 2. INICIALIZAR DRIVER ==========
        with st.spinner("🌐 Inicializando navegador..."):
            driver = WebDriverManager.criar_driver(headless=not DEBUG_MODE)
            wait = WebDriverWait(driver, config.timeout_elemento)
            
            st.success("✅ Navegador iniciado")
        
        # ========== 3. REALIZAR LOGIN ==========
        st.markdown("---")
        st.subheader("🔐 Autenticação")
        
        login_manager = LoginManager(driver, wait, config)
        
        if not login_manager.realizar_login(usuario, senha):
            st.error("❌ Não foi possível realizar o login. Processo interrompido.")
            driver.quit()
            return
        
        # ========== 4. PROCESSAR AUTOS ==========
        st.markdown("---")
        st.subheader("🚀 Processamento de Autos")
        
        consultor = ConsultorANTT(driver, wait, config)
        
        # Containers de feedback
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        col1, col2, col3 = st.columns(3)
        metric_sucesso = col1.empty()
        metric_erro = col2.empty()
        metric_processados = col3.empty()
        
        preview_container = st.expander("📋 Preview dos Resultados", expanded=True)
        
        # Contadores
        sucesso_count = 0
        erro_count = 0
        nao_encontrado_count = 0
        
        # Loop de processamento
        for idx, (original_idx, row) in enumerate(df_filtrado.iterrows()):
            auto = str(row[config.col_auto]).strip()
            
            # Atualiza status
            status_text.markdown(
                f"**Processando:** `{auto}` ({idx+1}/{total})"
            )
            
            # Atualiza métricas
            metric_processados.metric("📊 Processados", f"{idx+1}/{total}")
            metric_sucesso.metric("✅ Sucesso", sucesso_count)
            metric_erro.metric("❌ Erros", erro_count + nao_encontrado_count)
            
            # Processa auto
            resultado = consultor.processar_auto(auto)
            
            # Atualiza dataframe
            df.at[original_idx, config.col_status] = str(resultado['mensagem'])
            
            if resultado['status'] == 'sucesso':
                d = resultado['dados']
                df.at[original_idx, config.col_processo] = str(d.get('processo', ''))
                df.at[original_idx, config.col_data] = str(d.get('data_infracao', ''))
                df.at[original_idx, config.col_codigo] = str(d.get('codigo', ''))
                df.at[original_idx, config.col_fato] = str(d.get('fato', ''))
                df.at[original_idx, config.col_andamento] = str(d.get('andamento', ''))
                df.at[original_idx, config.col_data_andamento] = str(d.get('data_andamento', ''))
                sucesso_count += 1
            
            elif resultado['status'] == 'nao_encontrado':
                nao_encontrado_count += 1
            
            else:
                erro_count += 1
            
            # Atualiza barra de progresso
            progress_bar.progress((idx + 1) / total)
            
            # Mostra preview das últimas 10 linhas processadas
            with preview_container:
                df_preview = df[df[config.col_status] != ''].tail(10)
                st.dataframe(
                    df_preview[[
                        config.col_auto, 
                        config.col_processo,
                        config.col_andamento,
                        config.col_status
                    ]],
                    use_container_width=True
                )
            
            # Delay entre requisições (evitar bloqueio)
            time.sleep(0.8)
        
        # ========== 5. FINALIZAÇÃO ==========
        driver.quit()
        
        status_text.empty()
        progress_bar.empty()
        
        st.markdown("---")
        st.success("🎉 **Processamento Concluído!**")
        
        # Estatísticas finais
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("✅ Sucesso", sucesso_count)
        col2.metric("❌ Erros", erro_count)
        col3.metric("🔍 Não Encontrados", nao_encontrado_count)
        col4.metric("📊 Total", total)
        
        # ========== 6. DOWNLOAD DO RESULTADO ==========
        st.markdown("---")
        
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        nome_arquivo = f"ANTT_Resultado_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        st.download_button(
            label="📥 Baixar Planilha Completa",
            data=output,
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )
        
        st.balloons()
    
    except Exception as e:
        st.error(f"❌ **Erro Crítico:** {str(e)}")
        
        if DEBUG_MODE:
            st.exception(e)
        
        logger.exception("Erro no processamento")

# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
def main():
    """Interface principal da aplicação"""
    
    config = Config()
    
    # ========== CABEÇALHO ==========
    st.title("🚛 Robô ANTT - Consulta Automatizada")
    st.markdown(
        """
        Sistema automatizado para consulta de autos de infração no portal da ANTT.
        Processe planilhas completas de forma rápida e eficiente.
        """
    )
    st.markdown("---")
    
    # ========== SIDEBAR COM INSTRUÇÕES ==========
    with st.sidebar:
        st.header("ℹ️ Como Usar")
        
        st.markdown("""
        ### 📋 Passo a Passo
        
        1. **Credenciais:** Insira usuário e senha ANTT
        2. **Planilha:** Faça upload do arquivo Excel
        3. **Processar:** Clique no botão iniciar
        4. **Aguardar:** Acompanhe o progresso
        5. **Baixar:** Download do resultado
        
        ### 📊 Formato da Planilha
        
        - **Obrigatório:** Coluna "Auto de Infração"
        - **Formato:** Arquivo `.xlsx` (Excel)
        - **Limite recomendado:** 50 autos por vez
        
        ### ⚙️ Colunas Geradas
        
        - Nº do Processo
        - Data da Infração
        - Código da Infração
        - Fato Gerador
        - Último Andamento
        - Data do Último Andamento
        - Status da Consulta
        """)
        
        st.markdown("---")
        
        st.info("💡 **Dica:** Ative o modo debug para diagnóstico detalhado de problemas")
        
        st.markdown("---")
        
        st.caption("Desenvolvido com Streamlit + Selenium")
    
    # ========== FORMULÁRIO ==========
    st.subheader("🔐 Credenciais ANTT")
    
    col1, col2 = st.columns(2)
    
    with col1:
        usuario = st.text_input(
            "👤 Usuário",
            key="usuario",
            help="Seu usuário de acesso ao sistema ANTT"
        )
    
    with col2:
        senha = st.text_input(
            "🔒 Senha",
            type="password",
            key="senha",
            help="Sua senha de acesso ao sistema ANTT"
        )
    
    st.markdown("---")
    st.subheader("📂 Upload da Planilha")
    
    arquivo = st.file_uploader(
        "Selecione o arquivo Excel (.xlsx)",
        type=['xlsx'],
        help="A planilha deve conter a coluna 'Auto de Infração'"
    )
    
    # ========== VALIDAÇÕES ==========
    if not usuario or not senha:
        st.warning("⚠️ Por favor, preencha usuário e senha")
        st.stop()
    
    if not arquivo:
        st.info("📤 Aguardando upload da planilha...")
        st.stop()
    
    # ========== BOTÃO DE PROCESSAMENTO ==========
    st.markdown("---")
    
    if st.button(
        "🚀 Iniciar Processamento",
        type="primary",
        use_container_width=True
    ):
        processar_planilha(arquivo, usuario, senha, config)

# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    main()
