import sys
import numpy as np
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# The joblib library needs the exact class definition available in the __main__ module to unpickle successfully.
# This utility injects the necessary classes into the execution context.
def inject_model_classes():
    class StackingEnsemble:
        def __init__(self):
            self.xgb = xgb.XGBClassifier(
                n_estimators=300, 
                max_depth=5, 
                learning_rate=0.03, 
                scale_pos_weight=25,
                eval_metric='logloss',
                random_state=42
            )
            self.rf = RandomForestClassifier(
                n_estimators=300, 
                max_depth=10, 
                class_weight='balanced_subsample', 
                random_state=42
            )
            self.meta = LogisticRegression(class_weight='balanced')
            self.scaler = StandardScaler()

        def fit(self, X, y):
            pass

        def predict_proba(self, X):
            Xs = self.scaler.transform(X)
            p1 = self.xgb.predict_proba(X)[:, 1]
            p2 = self.rf.predict_proba(X)[:, 1]
            return self.meta.predict_proba(np.column_stack((p1, p2)))[:, 1]

        def predict(self, X):
            return (self.predict_proba(X) >= 0.5).astype(int)

    # Inject into the main module namespace where unpickling happens
    setattr(sys.modules['__main__'], 'StackingEnsemble', StackingEnsemble)
