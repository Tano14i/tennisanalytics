import streamlit as st
import data_provider as dp
import analytics as an
import main as mn

# Configurazione della pagina del browser
st.set_page_config(page_title="Tennis Content Analytics", page_icon="🎾", layout="centered")

st.title("🎾 Tennis Analytics Bot")
st.subheader("B2B Dashboard for Content Creators & Tipsters")
st.write("Genera in 5 secondi insight contestuali e grafiche pronte per Telegram/Discord.")

st.markdown("---")

# Interfaccia di Input
col1, col2 = st.columns(2)

with col1:
    player1 = st.selectbox("Seleziona il Giocatore 1", dp.list_players(), index=0)
    tournament = st.selectbox("Seleziona il Torneo", list(dp.TOURNAMENT_SURFACES.keys()), index=0)

with col2:
    available_p2 = [p for p in dp.list_players() if p != player1]
    player2 = st.selectbox("Seleziona il Giocatore 2", available_p2, index=0)
    
    surface = dp.TOURNAMENT_SURFACES.get(tournament, "Hard")
    st.info(f"Surface rilevata: **{surface}**")

st.markdown("---")

# Pulsante di calcolo
if st.button("🚀 GENERA REPORT PER TELEGRAM", use_container_width=True):
    with st.spinner("L'algoritmo sta analizzando la superficie e calcolando la curva del momentum..."):
        try:
            # 1. Estrazione dati grezzi
            p1_data = dp.get_player(player1)
            p2_data = dp.get_player(player2)
            
            # 2. Calcolo metriche per singolo giocatore
            p1_stats = an.compute_all(p1_data, surface)
            p2_stats = an.compute_all(p2_data, surface)

            # 3. Formattazione del post finale
            # format_post builds the insight internally — no need to call
            # build_insight separately. Pass full names from the player dicts.
            final_post = mn.format_post(
                player1, p1_data["full_name"], p1_stats,
                player2, p2_data["full_name"], p2_stats,
                tournament, surface,
            )
            
            # Mostriamo l'output a schermo
            st.success("Report Generato con Successo!")
            
            st.text_area(
                label="Copia e incolla direttamente sul tuo canale:",
                value=final_post,
                height=420
            )
            
            st.caption("💡 Suggerimento per il tipster: Fai uno screenshot della tabella sopra per i tuoi canali visuali.")
            
        except Exception as e:
            st.error(f"Errore durante il calcolo: {e}")