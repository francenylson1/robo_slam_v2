import sqlite3
import json
from src.core.config import DATABASE_PATH, MAP_WIDTH, MAP_HEIGHT
import os
from typing import List, Tuple, Optional, Dict

class MapManager:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self.conn = None
        self.cursor = None
        self._ensure_data_directory_exists()
        self._connect_db()
        self._create_tables()

    def _ensure_data_directory_exists(self):
        """Cria o diretório 'data' se ele não existir."""
        data_dir = os.path.dirname(self.db_path)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir)
            print(f"Diretório de dados criado: {data_dir}")

    def _connect_db(self):
        """Conecta ao banco de dados SQLite."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            print(f"Conectado ao banco de dados: {self.db_path}")
        except sqlite3.Error as e:
            print(f"Erro ao conectar ao banco de dados: {e}")

    def _create_tables(self):
        """Cria as tabelas necessárias no banco de dados."""
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return
        try:
            # Tabela mapas
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS mapas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE,
                    largura REAL NOT NULL,
                    comprimento REAL NOT NULL,
                    ativo INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Tabela pontos_interesse
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS pontos_interesse (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mapa_id INTEGER NOT NULL,
                    nome TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    tipo TEXT,
                    raio REAL,
                    FOREIGN KEY (mapa_id) REFERENCES mapas(id) ON DELETE CASCADE
                )
            """)
            # Tabela areas_proibidas
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS areas_proibidas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mapa_id INTEGER NOT NULL,
                    nome TEXT,
                    coordenadas TEXT NOT NULL,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    motivo TEXT,
                    FOREIGN KEY (mapa_id) REFERENCES mapas(id) ON DELETE CASCADE
                )
            """)
            # Tabela pid_gains (NOVO)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS pid_gains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    gains_json TEXT NOT NULL
                )
            """)
            self.conn.commit()
            print("Tabelas verificadas/criadas com sucesso.")
        except sqlite3.Error as e:
            print(f"Erro ao criar tabelas: {e}")

    def save_map(self, map_name: str, points_of_interest: dict, forbidden_areas: list):
        """
        Salva o mapa atual no banco de dados.
        Atualiza um mapa existente ou cria um novo.
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return
            
        try:
            self.cursor.execute("SELECT id FROM mapas WHERE nome = ?", (map_name,))
            map_id = self.cursor.fetchone()

            if map_id:
                map_id = map_id[0]
                # Atualiza o mapa existente, desativa outros e define este como ativo
                self.cursor.execute("UPDATE mapas SET ativo = 0")
                self.cursor.execute("UPDATE mapas SET largura = ?, comprimento = ?, ativo = 1 WHERE id = ?",
                                    (MAP_WIDTH, MAP_HEIGHT, map_id))
                # Limpa pontos de interesse e áreas proibidas antigas
                self.cursor.execute("DELETE FROM pontos_interesse WHERE mapa_id = ?", (map_id,))
                self.cursor.execute("DELETE FROM areas_proibidas WHERE mapa_id = ?", (map_id,))
                print(f"Mapa '{map_name}' atualizado.")
            else:
                # Insere novo mapa e o define como ativo, desativando outros
                self.cursor.execute("UPDATE mapas SET ativo = 0")
                self.cursor.execute("INSERT INTO mapas (nome, largura, comprimento, ativo) VALUES (?, ?, ?, 1)",
                                    (map_name, MAP_WIDTH, MAP_HEIGHT))
                map_id = self.cursor.lastrowid
                print(f"Novo mapa '{map_name}' criado.")

            # Insere pontos de interesse
            for name, data in points_of_interest.items():
                if isinstance(data, tuple):
                    if len(data) == 2:
                        # Formato antigo: (x, y)
                        x, y = data
                        point_type = "Mesa"  # Tipo padrão
                    else:
                        # Novo formato: (x, y, tipo)
                        x, y, point_type = data
                    self.cursor.execute("INSERT INTO pontos_interesse (mapa_id, nome, x, y, tipo) VALUES (?, ?, ?, ?, ?)",
                                        (map_id, name, x, y, point_type))

            # Insere áreas proibidas
            for area in forbidden_areas:
                if isinstance(area, dict):
                    # Novo formato: dicionário com id, nome, coordenadas
                    coordinates = area.get('coordenadas', [])
                    area_name = area.get('nome')
                else:
                    # Formato antigo: lista de coordenadas
                    coordinates = area
                    area_name = None
                
                # Converte lista de coordenadas para string JSON
                coords_json = json.dumps(coordinates)
                self.cursor.execute("INSERT INTO areas_proibidas (mapa_id, nome, coordenadas) VALUES (?, ?, ?)",
                                    (map_id, area_name, coords_json))

            self.conn.commit()
            print("Dados do mapa salvos com sucesso.")
        except sqlite3.Error as e:
            print(f"Erro ao salvar mapa: {e}")
            if self.conn:
                self.conn.rollback()

    def load_active_map(self) -> tuple[dict, list, str, Optional[int]]:
        """
        Carrega o mapa ativo do banco de dados.
        Retorna (points_of_interest, forbidden_areas, map_name, map_id).
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return {}, [], "", None

        points_of_interest = {}
        forbidden_areas = []
        map_name = ""
        map_id = None
        try:
            self.cursor.execute("SELECT id, nome FROM mapas WHERE ativo = 1")
            active_map = self.cursor.fetchone()

            if active_map:
                map_id, map_name = active_map
                print(f"Carregando mapa ativo: '{map_name}' (ID: {map_id})")

                # Carrega pontos de interesse
                self.cursor.execute("SELECT nome, x, y, tipo FROM pontos_interesse WHERE mapa_id = ?", (map_id,))
                for row in self.cursor.fetchall():
                    name, x, y, point_type = row
                    points_of_interest[name] = (x, y, point_type)

                # Carrega áreas proibidas com IDs
                areas_with_ids = self.get_forbidden_areas_with_ids(map_id)
                forbidden_areas = areas_with_ids

            else:
                print("Nenhum mapa ativo encontrado. Iniciando com mapa vazio.")

        except sqlite3.Error as e:
            print(f"Erro ao carregar mapa: {e}")

        return points_of_interest, forbidden_areas, map_name, map_id

    def get_all_map_names(self) -> list[str]:
        """
        Retorna uma lista com os nomes de todos os mapas salvos.
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return []
        try:
            self.cursor.execute("SELECT nome FROM mapas ORDER BY nome")
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao listar mapas: {e}")
            return []

    def load_map_by_name(self, map_name: str) -> tuple[dict, list, str, Optional[int]]:
        """
        Carrega um mapa específico pelo nome e o define como ativo.
        Retorna (points_of_interest, forbidden_areas, map_name, map_id).
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return {}, [], "", None

        try:
            # Desativa todos os mapas e ativa o selecionado
            self.cursor.execute("UPDATE mapas SET ativo = 0")
            self.cursor.execute("UPDATE mapas SET ativo = 1 WHERE nome = ?", (map_name,))
            self.conn.commit()

            # Agora carrega o mapa recém-ativado
            return self.load_active_map()

        except sqlite3.Error as e:
            print(f"Erro ao carregar mapa por nome: {e}")
            if self.conn:
                self.conn.rollback()
        return {}, [], "", None

    def get_pid_gains(self):
        """Busca os últimos ganhos de PID salvos no banco de dados."""
        try:
            self.cursor.execute("SELECT gains_json FROM pid_gains ORDER BY id DESC LIMIT 1")
            result = self.cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        except sqlite3.Error as e:
            print(f"Erro ao buscar ganhos do PID: {e}")
            return None

    def close(self):
        """Fecha a conexão com o banco de dados."""
        if self.conn:
            self.conn.close()
            print("Conexão com o banco de dados fechada.")

    def get_forbidden_areas(self, map_id: int) -> List[List[Tuple[float, float]]]:
        """Obtém todas as áreas proibidas de um mapa"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT coordenadas FROM areas_proibidas 
                    WHERE mapa_id = ? AND ativo = 1
                """, (map_id,))
                areas = []
                for row in cursor.fetchall():
                    # [CORREÇÃO] Troca eval por json.loads para segurança
                    coords_str = row[0]
                    coords_list = json.loads(coords_str)
                    areas.append([(float(x), float(y)) for x, y in coords_list])
                return areas
        except Exception as e:
            print(f"Erro ao obter áreas proibidas: {e}")
            return []

    def get_active_map(self) -> Optional[Dict]:
        """Obtém o mapa ativo do banco de dados"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, nome, largura, comprimento 
                    FROM mapas 
                    WHERE ativo = 1
                """)
                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'nome': row[1],
                        'largura': row[2],
                        'comprimento': row[3]
                    }
                return None
        except Exception as e:
            print(f"Erro ao obter mapa ativo: {e}")
            return None

    def save_forbidden_area(self, area_coordinates: List[Tuple[float, float]], area_name: Optional[str] = None) -> bool:
        """
        Salva uma área proibida individual no mapa ativo.
        
        Args:
            area_coordinates: Lista de coordenadas (x, y) da área
            area_name: Nome opcional para a área
            
        Returns:
            bool: True se salvou com sucesso, False caso contrário
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return False
            
        try:
            # Obtém o mapa ativo
            self.cursor.execute("SELECT id FROM mapas WHERE ativo = 1")
            active_map = self.cursor.fetchone()
            
            if not active_map:
                print("Erro: Nenhum mapa ativo encontrado.")
                return False
                
            map_id = active_map[0]
            
            # Converte lista de tuplas para string JSON
            coords_json = json.dumps(area_coordinates)
            
            # Insere a área proibida
            self.cursor.execute(
                "INSERT INTO areas_proibidas (mapa_id, nome, coordenadas) VALUES (?, ?, ?)",
                (map_id, area_name, coords_json)
            )
            
            self.conn.commit()
            print(f"Área proibida salva com sucesso. ID: {self.cursor.lastrowid}")
            return True
            
        except sqlite3.Error as e:
            print(f"Erro ao salvar área proibida: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def delete_forbidden_area(self, area_id: int) -> bool:
        """
        Remove uma área proibida específica.
        
        Args:
            area_id: ID da área proibida a ser removida
            
        Returns:
            bool: True se removeu com sucesso, False caso contrário
        """
        print(f"DEBUG: Tentando excluir área proibida ID: {area_id}")
        
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return False
            
        try:
            # Primeiro verifica se a área existe
            if self.cursor:
                self.cursor.execute("SELECT id, nome FROM areas_proibidas WHERE id = ?", (area_id,))
                area = self.cursor.fetchone()
                if area:
                    print(f"DEBUG: Área encontrada - ID: {area[0]}, Nome: {area[1]}")
                else:
                    print(f"DEBUG: Área {area_id} não encontrada no banco")
                    return False
                
                # Executa a exclusão
                self.cursor.execute("DELETE FROM areas_proibidas WHERE id = ?", (area_id,))
                self.conn.commit()
                
                print(f"DEBUG: rowcount após exclusão: {self.cursor.rowcount}")
                
                if self.cursor.rowcount > 0:
                    print(f"Área proibida {area_id} removida com sucesso.")
                    return True
                else:
                    print(f"Área proibida {area_id} não encontrada.")
                    return False
            else:
                print("Erro: Cursor não disponível")
                return False
                
        except sqlite3.Error as e:
            print(f"Erro ao remover área proibida: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def get_forbidden_areas_with_ids(self, map_id: Optional[int] = None) -> List[Dict]:
        """
        Obtém todas as áreas proibidas de um mapa com seus IDs.
        
        Args:
            map_id: ID do mapa (se None, usa o mapa ativo)
            
        Returns:
            Lista de dicionários com id, nome, coordenadas e ativo
        """
        if not self.conn or not self.cursor:
            print("Erro: Conexão com o banco de dados não estabelecida.")
            return []
            
        try:
            if map_id is None:
                # Obtém o mapa ativo
                self.cursor.execute("SELECT id FROM mapas WHERE ativo = 1")
                active_map = self.cursor.fetchone()
                if not active_map:
                    return []
                map_id = active_map[0]
            
            self.cursor.execute("""
                SELECT id, nome, coordenadas, ativo 
                FROM areas_proibidas 
                WHERE mapa_id = ? AND ativo = 1
                ORDER BY id
            """, (map_id,))
            
            areas = []
            for row in self.cursor.fetchall():
                area_id, name, coords_json, active = row
                try:
                    # Tenta carregar como JSON primeiro
                    coords_list = json.loads(coords_json)
                except (json.JSONDecodeError, TypeError):
                    try:
                        # Se falhar, tenta usar eval (formato antigo)
                        coords_list = eval(coords_json)
                    except Exception as e:
                        print(f"DEBUG: Erro ao carregar coordenadas da área {area_id}: {e}")
                        print(f"DEBUG: Dados: {coords_json[:100]}...")
                        continue
                
                # Verifica se as coordenadas são válidas
                if not isinstance(coords_list, list):
                    print(f"DEBUG: Coordenadas inválidas para área {area_id}: {coords_list}")
                    continue
                    
                # Verifica se cada coordenada é válida
                valid_coords = []
                for coord in coords_list:
                    if isinstance(coord, list) and len(coord) == 2:
                        try:
                            x, y = float(coord[0]), float(coord[1])
                            valid_coords.append([x, y])
                        except (ValueError, TypeError):
                            print(f"DEBUG: Coordenada inválida na área {area_id}: {coord}")
                            continue
                    else:
                        print(f"DEBUG: Formato de coordenada inválido na área {area_id}: {coord}")
                        continue
                
                if valid_coords:
                    areas.append({
                        'id': area_id,
                        'nome': name,
                        'coordenadas': valid_coords,
                        'ativo': bool(active)
                    })
                    print(f"DEBUG: Área {area_id} carregada com {len(valid_coords)} coordenadas válidas")
                else:
                    print(f"DEBUG: Área {area_id} sem coordenadas válidas")
            
            return areas
            
        except sqlite3.Error as e:
            print(f"Erro ao obter áreas proibidas: {e}")
            return []

    def get_points_of_interest(self, map_id: int) -> Dict[str, Tuple[float, float, str]]:
        """Obtém todos os pontos de interesse de um mapa."""
        points = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT nome, x, y, tipo FROM pontos_interesse WHERE mapa_id = ?
                """, (map_id,))
                for row in cursor.fetchall():
                    name, x, y, point_type = row
                    points[name] = (x, y, point_type)
        except Exception as e:
            print(f"Erro ao obter pontos de interesse: {e}")
        return points 