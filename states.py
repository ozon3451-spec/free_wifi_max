# States.py
# Состояния пользователей бота

from datetime import datetime, timedelta



# Менеджер состояний


class StateManager:

    def __init__(self):
        self._states = {}


   
    # Установить состояние
   

    def set_state(self, user_id, state_name, data=None):
        self._states[str(user_id)] = {
            "state": state_name,
            "data": data or {},
            "updated_at": datetime.now()
        }


    
    # Получить состояние
    

    def get_state(self, user_id):
        user_id = str(user_id)

        if user_id not in self._states:
            return None, {}

        # Состояние автоматически удаляется через 10 минут
        if (
            datetime.now()
            - self._states[user_id]["updated_at"]
            > timedelta(minutes=10)
        ):
            self.clear_state(user_id)
            return None, {}

        return (
            self._states[user_id]["state"],
            self._states[user_id]["data"]
        )


    
    # Удалить состояние
    

    def clear_state(self, user_id):
        self._states.pop(str(user_id), None)


# Один общий менеджер состояний
state_mgr = StateManager()